## Deoracle

A decentralized oracle is a system that provides external, real-world data to blockchain networks and smart contracts in a trustless and decentralized manner.
It uses [Olas](https://olas.network/) agents and [Open Autonomy](https://github.com/valory-xyz/open-autonomy).


## System requirements

- Python `>=3.10`
- [Tendermint](https://docs.tendermint.com/v0.34/introduction/install.html) `==0.34.19`
- [IPFS node](https://docs.ipfs.io/install/command-line/#official-distributions) `==0.6.0`
- [Pip](https://pip.pypa.io/en/stable/installation/)
- [Poetry](https://python-poetry.org/)
- [Docker Engine](https://docs.docker.com/engine/install/)
- [Docker Compose](https://docs.docker.com/compose/install/)
- [Set Docker permissions so you can run containers as non-root user](https://docs.docker.com/engine/install/linux-postinstall/)


## Run you own agent

### Get the code

1. Clone this repo:

    ```
    git clone https://github.com/Suvadra-Barua/deoracle.git
    ```

2. Create the virtual environment:

    ```
    cd deoracle
    poetry shell
    poetry install
    ```

3. Sync packages:

    ```
    autonomy packages sync --update-packages
    ```

### Prepare the data

1. Prepare a keys.json file containing wallet address and the private key for each of the four agents.

    ```
    autonomy generate-key ethereum -n 4
    ```

2. Prepare a `ethereum_private_key.txt` file containing one of the private keys from `keys.json`. Ensure that there is no newline at the end.

3. Deploy two [Safes on Gnosis](https://app.safe.global/welcome) (it's free) and set your agent addresses as signers. Set the signature threshold to 1 out of 4 for one of them and and to 3 out of 4 for the other. This way we can use the single-signer one for testing without running all the agents, and leave the other safe for running the whole service.

4. Create a [Tenderly](https://tenderly.co/) account and from your dashboard create a fork of Gnosis chain (virtual testnet).

5. From Tenderly, fund your agents and Safe with some xDAI .

6. Make a copy of the env file:

    ```
    cp sample.env .env
    ```
7. Set up deoracle contracts:
    - Clone the [deoracle-contracts](https://github.com/Suvadra-Barua/deoracle-contracts.git) repo
    - Set up the RPC under `tenderly` in hardhat config
    - Run deploy script using the command `npx hardhat run scripts/deploy.ts --network tenderly` and get the deployed address
    - Use the address in `scripts/contractInteractions.ts` script

8. Fill in the required environment variables in .env. These variables are:
- `ALL_PARTICIPANTS`: a list of your agent addresses. This will vary depending on whether you are running a single agent (`run_agent.sh` script) or the whole 4-agent service (`run_service.sh`)
- `GNOSIS_LEDGER_RPC`: set it to your Tenderly fork Admin RPC. (Use same RPC you used in `deoracle-contracts` hardhat.config.ts
- `TRANSFER_TARGET_ADDRESS`: any random address to send funds to, can be any of the agents for example.
- `SAFE_CONTRACT_ADDRESS_SINGLE`: the 1 out of 4 agents Safe address.
- `SAFE_CONTRACT_ADDRESS`: the 3 out of 4 Safe address.
- `WEATHER_ORACLE_ADDRESS`: deploy [deoracle-contracts](https://github.com/Suvadra-Barua/deoracle-contracts.git) to Tenderly and set the address here
- `FROM_BLOCK`: event listening starts from this block
- `TO_BLOCK`: event listening ends to this block
- `WEATHERSTACK_PARAMETERS`:`'{"access_key":"","query":""}'. [WeatherStack](https://weatherstack.com/)


### Run a single agent locally

1. Verify that `ALL_PARTICIPANTS` in `.env` contains only 1 address.

2. Run the agent:

    ```
    bash run_agent.sh
    ```
3. When it starts round, run the `scripts/contractInteractions.ts` using the command `npx hardhat run scripts/contractInteractions.ts --network tenderly` from `deoracle-contracts` repo in another terminal
### Run the service (4 agents) via Docker Compose deployment

1. Verify that `ALL_PARTICIPANTS` in `.env` contains 4 address.

2. Check that Docker is running:

    ```
    docker
    ```

3. Run the service:

    ```
    bash run_service.sh
    ```
4. When it starts round, run the `scripts/contractInteractions.ts` using the command `npx hardhat run scripts/contractInteractions.ts --network tenderly` from `deoracle-contracts` repo in another terminal
5. Look at the service logs for one of the agents (on another terminal):

    ```
    docker logs -f learningservice_abci_0
    ```
