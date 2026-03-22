# 🏛️ Polymarket Bot: System Architecture

This outlines the infrastructure and deployment pipeline for running the copy-bot safely across Local (your Macbook) and Remote (Hetzner Cloud) environments.

## Architecture Diagram

**1. Local Development Mac**
* **Code & Data**: You edit files like `database.py` in VS Code. `trading.db` is stored locally for testing.
* **Testing**: You run the Streamlit Dashboard and the `bot.py` loop locally to verify changes.
* **Deployment**: You run `git commit` and `git push` to send your code to the GitHub Repository.

**2. GitHub Actions (Automated CI/CD)**
* **Trigger**: A push to the `main` branch automatically alerts the Hetzner server to pull new changes.
* **Action**: Hetzner safely stops the current bot, rebuilds its Docker container, and pulls your latest code from GitHub.

**3. Hetzner Production Server**
* **Environment Variables**: The `.env` file (containing API/Private Keys) lives ONLY on the server and maps securely to the Docker instance.
* **Database**: `trading.db` runs live inside the container, tracking real trades.
* **Execution**: The Live Streamlit UI and Live Copy-Bot Daemon pull directly from this live `trading.db`. 

**4. External Protocols**
* The live Daemon scans the **Polymarket Protocol (Gamma API)** for open positions.
* It executes orders via the **CLOB API**.
* Profits are successfully transferred out to the **User's Main Safety Wallet**.

## Local vs Remote Workflow (Best Practices)

1. **Total Isolation**. Your Local Mac environment and your Hetzner Production environment operate completely isolated from one another. This is by design. You never want your local test server "subscribing" to your live production database, because hitting `start.sh` on your local laptop could accidentally fire live, real-money duplicate trades!
2. **Updating Traders.** When you want to permanently cement a new trader into your roster, you edit the "defaults" array in `database.py` locally and push to GitHub.
3. **Deploying.** You SSH into your Hetzner server and `git pull`. When you start your bot on Hetzner, the code detects the new python source file and dynamically reconstructs the live `trading.db` from those defaults without losing historical memory.
4. **Environment Variables.** The `.env` file containing your Private Keys, Alchemy endpoints, and Telegram IDs is strictly blocked from Github via `.gitignore`. You must log into Hetzner and type `nano .env` exactly once during initial setup to insert your secret keys. 

## What to do next to go live?
1. Edit `database.py`'s `defaults` array on your Mac to lock in the actual `0x...` hashes over any "MOCK_" placeholders.
2. Ensure you have your `BOT_PRIVATE_KEY` and `ALCHEMY_POLYGON_URL` mapped locally to test it end-to-end.
3. Push everything to your remote Github Repo.
4. Clone the Repo onto your Hetzner VPS.
5. Create `.env` on Hetzner and paste the keys in.
6. Trigger the start script via a screen or daemon!
