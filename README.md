# 📊 Polymarket Specialist Copy-Bot

An automated trading bot for Polymarket that mirrors the trades of high-performing specialists using Web3 execution (ethers.py/web3.py). It features intelligent position sizing (Dynamic 15% Kelly Criterion), adaptive value caps, and automatic profit harvesting.

## 🚀 Features
- **Dynamic Sizing**: Calculates maximum downside and adjusts sizes automatically based on a $50 baseline.
- **2x Harvest Rule**: Automatically sweeps profits to a secondary, non-trading wallet once returns hit double the baseline.
- **Adaptive Value Caps**: Distinguishes between fast-resolving markets (e.g., NBA) and long-tail events (e.g., Elections), capping entry prices accordingly.
- **Web Dashboard**: An integrated Streamlit UI to monitor growth, trade history, and active Alpha wallets.

---

## 🛠 Deployment & Setup (Continuous Deployment)

This repository is designed to be deployed automatically using a Platform-as-a-Service (PaaS) like **Render** or **Railway**. By connecting this GitHub repository to the platform, any new push to the `main` branch will automatically redeploy the bot and dashboard.

### 1. Local Development
1. Clone this repository to your local machine:
   ```bash
   git clone <YOUR_GITHUB_REPO_URL>
   cd polymarket-picks
   ```
2. Create your local `.env` file (this is ignored by Git for security):
   ```env
   BOT_PRIVATE_KEY=your_new_dedicated_wallet_pk
   HARVEST_WALLET_ADDRESS=your_personal_wallet_for_profits
   ALCHEMY_POLYGON_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
   ```
3. Install dependencies and run:
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   # Or run the bot headless
   python bot.py
   ```

### 2. Connect to a Cloud Platform (Render/Railway)
1. **Push to GitHub**: Make sure your code is committed and pushed to a remote GitHub repository.
2. **Create a New Web Service**: Log into Render or a similar PaaS, and create a new **Web Service**.
3. **Connect Repository**: Authorize the platform to pull from your GitHub repository.
4. **Configure Environment Variables**: In the dashboard of the cloud platform, add the contents of your `.env` file as Environment Variables/Secrets:
   - `BOT_PRIVATE_KEY`
   - `HARVEST_WALLET_ADDRESS`
   - `ALCHEMY_POLYGON_URL`
5. **Set the Run Command**: 
   Since we provide a `Dockerfile`, you can simply select **Docker** as the environment, and the platform will automatically build and expose the Streamlit port (`8501`) and run `bot.py` alongside it.

Now, whenever you run `git push`, the remote server will automatically update your bot without manual intervention!

---

*Bot built successfully with 15% Position Sizing & 2x Dynamic Harvesting logic embedded.*
