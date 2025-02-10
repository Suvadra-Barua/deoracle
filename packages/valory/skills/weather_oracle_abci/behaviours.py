# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This package contains round behaviours of WeatherOracleAbciApp."""

import json
from abc import ABC
from pathlib import Path
from tempfile import mkdtemp
from typing import Dict, Generator, Optional, Set, Type, cast

from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.multisend.contract import (
    MultiSendContract,
    MultiSendOperation,
)
from packages.valory.contracts.weather_oracle.contract import WeatherOracle
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.ledger_api import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.base import AbstractRound
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.abstract_round_abci.io_.store import SupportedFiletype
from packages.valory.skills.weather_oracle_abci.models import (
    WeatherstackSpecs,
    Params,
    SharedState,
)
from packages.valory.skills.weather_oracle_abci.payloads import (
    OracleDataPullPayload,
    DecisionMakingPayload,
    OracleTxPreparationPayload,
    RequestDataPullPayload,
    
)
from packages.valory.skills.weather_oracle_abci.rounds import (
    OracleDataPullRound,
    DecisionMakingRound,
    Event,
    WeatherOracleAbciApp,
    RequestDataPullRound,
    SynchronizedData,
    OracleTxPreparationRound,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


# Define some constants
ZERO_VALUE = 0
HTTP_OK = 200
GNOSIS_CHAIN_ID = "gnosis"
EMPTY_CALL_DATA = b"0x"
SAFE_GAS = 0
VALUE_KEY = "value"
TO_ADDRESS_KEY = "to_address"
METADATA_FILENAME = "metadata.json"


class OracleBaseBehaviour(BaseBehaviour, ABC):  # pylint: disable=too-many-ancestors
    """Base behaviour for the weather_oracle_abci behaviours."""

    @property
    def params(self) -> Params:
        """Return the params. Configs go here"""
        return cast(Params, super().params)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data. This data is common to all agents"""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def local_state(self) -> SharedState:
        """Return the local state of this particular agent."""
        return cast(SharedState, self.context.state)

    @property
    def weatherstack_specs(self) -> WeatherstackSpecs:
        """Get the WeatherStack API specs."""
        return self.context.weatherstack_specs
    
    @property
    def metadata_filepath(self) -> str:
        """Get the temporary filepath to the metadata."""
        return str(Path(mkdtemp()) / METADATA_FILENAME)

    def get_sync_timestamp(self) -> float:
        """Get the synchronized time from Tendermint's last block."""
        now = cast(
            SharedState, self.context.state
        ).round_sequence.last_round_transition_timestamp.timestamp()

        return now

class RequestDataPullBehaviour(OracleBaseBehaviour):
    """This behaviour pulls requester query data from WeatherOracle"""

    matching_round: Type[AbstractRound] = RequestDataPullRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address
            location = yield from self.get_request_location()

            # Prepare the payload to be shared with other agents
            # After consensus, all the agents will have the same price, price_ipfs_hash and balance variables in their synchronized data
            payload = RequestDataPullPayload(
                sender=sender,
                location=location
            )

        # Send the payload to all agents and mark the behaviour as done
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
    
    def get_request_location(self) -> Generator[None, None, Optional[float]]:
        """Get location of a request id"""
        self.context.logger.info(
            f"Getting Requester's Query for Safe {self.synchronized_data.safe_contract_address}"
        )

        # Use the contract api to interact with the WeatherOracle contract
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.weather_oracle_address,
            contract_id=str(WeatherOracle.contract_id),
            contract_callable="get_weather_data",
            chain_id=GNOSIS_CHAIN_ID,
            request_id=0
        )

        # Check that the response is what we expect
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Error while retrieving the location: {response_msg}"
            )
            return None
        # print(f"The response msg is {response_msg}")
        data = response_msg.raw_transaction.body.get("data", None)
        location = data["location"]
        self.context.logger.info(
            f"The requester want to get weather data of the location : {location}"
        )
        return location
class OracleDataPullBehaviour(OracleBaseBehaviour):  # pylint: disable=too-many-ancestors
    """This behaviour pulls weather data from WeatherStack API and stores it in IPFS"""

    matching_round: Type[AbstractRound] = OracleDataPullRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address

            # Get request location that was set in previous round
            location = self.synchronized_data.request_location
            # Get weather data using ApiSpecs
            weather_data = yield from self.get_weather_data_specs(location)

            # Store the weather data in IPFS
            weather_ipfs_hash = yield from self.send_weather_to_ipfs(weather_data)

            print(f"The fetched weather data: {weather_data}")
            # Prepare the payload with Optional fields
            payload = OracleDataPullPayload(
                sender=sender,
                temperature=weather_data.get("temperature"),
                humidity=weather_data.get("humidity"),
                wind_speed=weather_data.get("wind_speed"),
                weather_ipfs_hash=weather_ipfs_hash,
            )

        # Send the payload and wait for consensus
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def get_weather_data_specs(self, location:str) -> Generator[None, None, Optional[Dict]]:
        """Get weather data from WeatherStack using ApiSpecs"""
        
        # Get the specs
        specs = self.weatherstack_specs.get_spec()

        # Get location from params and add to parameters
        specs["parameters"]["query"] = location

        print(f"The weather spec is",{**specs})
        
        # Make the call
        raw_response = yield from self.get_http_response(**specs)
        
        # Process the response
        response = self.weatherstack_specs.process_response(raw_response)
        
        # Get the weather data
        if response:
            weather_data = {
                "temperature": response.get("temperature"),
                "humidity": response.get("humidity"),
                "wind_speed": response.get("wind_speed")
            }
            self.context.logger.info(f"Got weather data from WeatherStack: {weather_data}")
            return weather_data
        
        self.context.logger.error("Failed to get weather data from WeatherStack")
        return None

    def send_weather_to_ipfs(self, weather) -> Generator[None, None, Optional[str]]:
        try:
            """Store the token price in IPFS"""
            data = {"weather": weather}
            weather_ipfs_hash = yield from self.send_to_ipfs(
                filename=self.metadata_filepath, obj=data, filetype=SupportedFiletype.JSON
            )
            self.context.logger.info(
                f"Weather data stored in IPFS: https://gateway.autonolas.tech/ipfs/{weather_ipfs_hash}"
            )
            return weather_ipfs_hash


        except Exception as e:
            self.context.logger.error(f"Error storing in IPFS: {str(e)}")
            return None
        


class DecisionMakingBehaviour(
    OracleBaseBehaviour
):  # pylint: disable=too-many-ancestors
    """DecisionMakingBehaviour"""

    matching_round: Type[AbstractRound] = DecisionMakingRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address

            # Make a decision: either transact or not
            event = yield from self.get_next_event()

            payload = DecisionMakingPayload(sender=sender, event=event)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def get_next_event(self) -> Generator[None, None, str]:
        """Get the next event: decide whether ot transact or not based on some data."""

        weather_data = yield from self.get_weather_data_from_ipfs()

        # If we fail to get the token balance, we send the ERROR event
        if not weather_data:
            self.context.logger.info(
                "Weather data is None. Sending the ERROR event..."
            )
            return Event.ERROR.value

        return Event.DONE.value

    def get_weather_data_from_ipfs(self) -> Generator[None, None, Optional[dict]]:
        """Load the price data from IPFS"""
        ipfs_hash = self.synchronized_data.weather_ipfs_hash
        weather = yield from self.get_from_ipfs(
            ipfs_hash=ipfs_hash, filetype=SupportedFiletype.JSON
        )
        self.context.logger.error(f"Got price from IPFS: {weather}")
        return weather


class OracleTxPreparationBehaviour(
    OracleBaseBehaviour
):  # pylint: disable=too-many-ancestors
    """OracleTxPreparationBehaviour"""

    matching_round: Type[AbstractRound] = OracleTxPreparationRound

    def async_act(self) -> Generator:
        """Do the act, supporting asynchronous execution."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            sender = self.context.agent_address

            # Get the transaction hash
            tx_hash = yield from self.get_tx_hash()

            payload = OracleTxPreparationPayload(
                sender=sender, tx_submitter=self.auto_behaviour_id(), tx_hash=tx_hash
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
    
    def get_update_weather_tx_data(self) -> Generator[None, None, Optional[str]]:
        """Get the update weather transaction data"""

        self.context.logger.info("Preparing Weather Update transaction")
        
        ipfs_hash = self.synchronized_data.weather_ipfs_hash

        # Use the contract api to interact with the WeatherOracle contract
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.weather_oracle_address,
            contract_id=str(WeatherOracle.contract_id),
            contract_callable="build_update_weather_tx",
            request_id=0,
            ipfs_hash=ipfs_hash,
            chain_id=GNOSIS_CHAIN_ID,
        )

        # Check that the response is what we expect
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Error while preparing response message for updating weather: {response_msg}"
            )
            return None

        data_bytes: Optional[bytes] = response_msg.raw_transaction.body.get(
            "data", None
        )

        # Ensure that the data is not None
        if data_bytes is None:
            self.context.logger.error(
                f"Error while preparing the transaction: {response_msg}"
            )
            return None

        data_hex = data_bytes.hex()
        self.context.logger.info(f"Update weather transaction data is {data_hex}")
        return data_hex

    def get_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Get the transaction hash"""

        # Multisend transaction (Only Update Weather) (Safe -> recipient)
        self.context.logger.info("Preparing a multisend transaction")
        tx_hash = yield from self.get_multisend_safe_tx_hash()
        return tx_hash

    def get_multisend_safe_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Get a multisend transaction hash"""
        # Step 1: we prepare a list of transactions
        # Step 2: we pack all the transactions in a single one using the mulstisend contract
        # Step 3: we wrap the multisend call inside a Safe call, as always

        multi_send_txs = []

        # Update weather
        update_weather_tx_data_hex = yield from self.get_update_weather_tx_data()

        if update_weather_tx_data_hex is None:
            return None

        multi_send_txs.append(
            {
                "operation": MultiSendOperation.CALL,
                "to": self.params.weather_oracle_address,
                "value": ZERO_VALUE,
                "data": bytes.fromhex(update_weather_tx_data_hex),
            }
        )

        # Multisend call
        contract_api_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.multisend_address,
            contract_id=str(MultiSendContract.contract_id),
            contract_callable="get_tx_data",
            multi_send_txs=multi_send_txs,
            chain_id=GNOSIS_CHAIN_ID,
        )

        # Check for errors
        if (
            contract_api_msg.performative
            != ContractApiMessage.Performative.RAW_TRANSACTION
        ):
            self.context.logger.error(
                f"Could not get Multisend tx hash. "
                f"Expected: {ContractApiMessage.Performative.RAW_TRANSACTION.value}, "
                f"Actual: {contract_api_msg.performative.value}"
            )
            return None

        # Extract the multisend data and strip the 0x
        multisend_data = cast(str, contract_api_msg.raw_transaction.body["data"])[2:]
        self.context.logger.info(f"Multisend data is {multisend_data}")

        # Prepare the Safe transaction
        safe_tx_hash = yield from self._build_safe_tx_hash(
            to_address=self.params.multisend_address,
            value=ZERO_VALUE,  # the safe is not moving any native value into the multisend
            data=bytes.fromhex(multisend_data),
            operation=SafeOperation.DELEGATE_CALL.value,  # we are delegating the call to the multisend contract
        )
        return safe_tx_hash

    def _build_safe_tx_hash(
        self,
        to_address: str,
        value: int = ZERO_VALUE,
        data: bytes = EMPTY_CALL_DATA,
        operation: int = SafeOperation.CALL.value,
    ) -> Generator[None, None, Optional[str]]:
        """Prepares and returns the safe tx hash for a multisend tx."""

        self.context.logger.info(
            f"Preparing Safe transaction [{self.synchronized_data.safe_contract_address}]"
        )

        # Prepare the safe transaction
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=to_address,
            value=value,
            data=data,
            safe_tx_gas=SAFE_GAS,
            chain_id=GNOSIS_CHAIN_ID,
            operation=operation,
        )

        # Check for errors
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                "Couldn't get safe tx hash. Expected response performative "
                f"{ContractApiMessage.Performative.STATE.value!r}, "  # type: ignore
                f"received {response_msg.performative.value!r}: {response_msg}."
            )
            return None

        # Extract the hash and check it has the correct length
        tx_hash: Optional[str] = response_msg.state.body.get("tx_hash", None)

        if tx_hash is None or len(tx_hash) != TX_HASH_LENGTH:
            self.context.logger.error(
                "Something went wrong while trying to get the safe transaction hash. "
                f"Invalid hash {tx_hash!r} was returned."
            )
            return None

        # Transaction to hex
        tx_hash = tx_hash[2:]  # strip the 0x

        safe_tx_hash = hash_payload_to_hex(
            safe_tx_hash=tx_hash,
            ether_value=value,
            safe_tx_gas=SAFE_GAS,
            to_address=to_address,
            data=data,
            operation=operation,
        )

        self.context.logger.info(f"Safe transaction hash is {safe_tx_hash}")

        return safe_tx_hash


class WeatherOracleRoundBehaviour(AbstractRoundBehaviour):
    """WeatherOracleRoundBehaviour"""

    initial_behaviour_cls = OracleDataPullBehaviour
    abci_app_cls = WeatherOracleAbciApp  # type: ignore
    behaviours: Set[Type[BaseBehaviour]] = [  # type: ignore
        RequestDataPullBehaviour,
        OracleDataPullBehaviour,
        DecisionMakingBehaviour,
        OracleTxPreparationBehaviour,
    ]
