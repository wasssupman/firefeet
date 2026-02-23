import streamlit as st
import pandas as pd
from core.config_loader import ConfigLoader
from core.kis_auth import KISAuth
from core.providers.kis_api import KISManager
from core.analysis.supply import SupplyAnalyzer
import time

# Page Config
st.set_page_config(page_title="Firefeet Dashboard", page_icon="🔥", layout="wide")

st.title("🔥 Firefeet Auto Trading System")

# Sidebar: Config
st.sidebar.header("Configuration")
mode = st.sidebar.radio("Mode", ["REAL", "PAPER"], index=0)
auto_refresh = st.sidebar.checkbox("Auto Refresh (60s)", value=False)

if auto_refresh:
    time.sleep(1)
    st.rerun()

# Initialize API
@st.cache_resource
def get_manager(mode):
    loader = ConfigLoader()
    config = loader.get_kis_config(mode=mode)
    account_info = loader.get_account_info()
    auth = KISAuth(config)
    auth.get_access_token() # Force Auth
    return KISManager(auth, account_info, mode=mode), SupplyAnalyzer(auth)

try:
    manager, supply_analyzer = get_manager(mode)
except Exception as e:
    st.error(f"Failed to connect to API: {e}")
    st.stop()

# 1. Account Status
st.header("1. Account Status 💰")
col1, col2 = st.columns(2)

try:
    balance = manager.get_balance()
    with col1:
        st.metric("Total Asset", f"{balance['total_asset']:,} KRW")
    with col2:
        st.metric("Deposit", f"{balance['deposit']:,} KRW")
    
    st.subheader("Holdings")
    if balance['holdings']:
        df_holdings = pd.DataFrame(balance['holdings'])
        st.dataframe(df_holdings, use_container_width=True)
    else:
        st.info("No holdings currently.")
except Exception as e:
    st.error(f"Error fetching balance: {e}")

# 2. Market Analysis
st.header("2. Supply/Demand Analysis 📊")
targets = [
    {"code": "005930", "name": "Samsung Electronics"},
    {"code": "000660", "name": "SK Hynix"},
    {"code": "005380", "name": "Hyundai Motor"}
]

for target in targets:
    with st.expander(f"{target['name']} ({target['code']})", expanded=True):
        try:
            result = supply_analyzer.analyze_supply(target['code'])
            if isinstance(result, str):
                st.warning(result)
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Sentiment", result['sentiment'])
                c2.metric("Foreigner (3D)", f"{result['foreign_3d']:,}")
                c3.metric("Institution (3D)", f"{result['institution_3d']:,}")
                
                # Chart
                recent_df = pd.DataFrame(result['recent_data'])
                st.bar_chart(recent_df.set_index('date')[['foreigner', 'institution']])
        except Exception as e:
            st.error(f"Analysis failed: {e}")

# 3. News Alerts (Simulation View)
st.header("3. News Alert System 📰")
st.info("News alerts are sent to Discord directly. Run `run_news_bot.py` to start the bot.")
st.markdown("""
**Monitoring Keywords:** `공시`, `계약`, `무상증자`, `유상증자`, `특허`, `수주`, `개발`, `임상`
""")

# Footer
st.markdown("---")
st.caption("Firefeet Trading System v1.0")
