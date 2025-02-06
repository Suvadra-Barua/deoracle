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

from typing import Dict

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi


PUBLIC_ID = PublicId.from_str("valory/weather_oracle:0.1.0")


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