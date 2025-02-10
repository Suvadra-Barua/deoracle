# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This module contains the class to connect to a Weather Oracle contract."""


import logging
from typing import Any, Dict, List, Optional, Union, cast

import web3
from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi


PUBLIC_ID = PublicId.from_str("valory/weather_oracle:0.1.0")

_logger = logging.getLogger(
    f"aea.packages.{PUBLIC_ID.author}.contracts.{PUBLIC_ID.name}.contract"
)

class WeatherOracle(Contract):
    """The Weather Oracle contract."""

    contract_id = PUBLIC_ID

    @classmethod
    def get_weather_data(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        request_id: int,
    ) -> JSONLike:
        """Get weather data for a specific request ID."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        weather_data = contract_instance.functions.getWeatherData(request_id).call()
        
        print(f"The weather data from contract:",{weather_data})
        return dict(
            data={
                "ipfsHash": weather_data[0],
                "location": weather_data[1],
                "timestamp": weather_data[2],
                "requester": weather_data[3],
                "fulfilled": weather_data[4]
            }
        )
    
    @classmethod
    def build_update_weather_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        request_id: int,
        ipfs_hash: str,
    ) -> Dict[str, bytes]:
        """Build a transaction to update weather data."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("updateWeather", args=(request_id, ipfs_hash))
        return {"data": bytes.fromhex(data[2:])}

    @classmethod
    def get_events(  # pylint: disable=too-many-arguments
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        event_name: str,
        from_block: Optional[int] = None,
        to_block: Union[int, str] = "latest",
    ) -> JSONLike:
        """Get events."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        current_block = ledger_api.api.eth.get_block_number()

        if from_block is None:
            from_block = current_block - 86400  # approx 48h ago (2s per block)

        # Avoid parsing too many blocks at a time. This might take too long and
        # the connection could time out.
        MAX_BATCH_BLOCKS = 5000

        to_block = current_block - 1 if to_block == "latest" else to_block

        _logger.info(
            f"Getting {event_name} events from block {from_block} to {to_block} ({int(to_block) - int(from_block)} blocks)"
        )

        ranges: List[int] = list(
            range(from_block, cast(int, to_block), MAX_BATCH_BLOCKS)
        ) + [cast(int, to_block)]

        event = getattr(contract_instance.events, event_name)
        events = []
        for i in range(len(ranges) - 1):
            from_block = ranges[i]
            to_block = ranges[i + 1]
            new_events = []

            _logger.info(f"Block batch {from_block} to {to_block}...")

            while True:
                try:
                    new_events = event.create_filter(
                        fromBlock=from_block,  # exclusive
                        toBlock=to_block,  # inclusive
                    ).get_all_entries()  # limited to 10k entries for now
                    break
                # Gnosis RPCs sometimes returns:
                # ValueError: Filter with id: x does not exist
                # MismatchedABI: The event signature did not match the provided ABI
                # Retrying several times makes it work
                except ValueError as e:
                    _logger.error(e)
                except web3.exceptions.MismatchedABI as e:
                    _logger.error(e)

            events += new_events

        _logger.info(f"Got {len(events)} {event_name} events")

        if event_name == "WeatherRequested":
            return dict(
                events=[
                    {
                        "requestId": e.args["requestId"],
                        "location": e.args["location"],
                        "timestamp": e.args["timestamp"],
                    }
                    for e in events
                ],
                latest_block=int(to_block),
            )

        return {}