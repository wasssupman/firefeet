class SupplyAnalyzer:
    def analyze_supply(self, df):
        """
        Analyzes recent supply trend.
        df: DataFrame of investor_trend
        """
        if df is None or df.empty:
            return "No Data"
            
        # Recent 3 days sum
        recent = df.head(3)
        foreign_sum = recent['foreigner'].sum()
        inst_sum = recent['institution'].sum()
        
        sentiment = "NEUTRAL"
        if foreign_sum > 0 and inst_sum > 0:
            sentiment = "BULLISH (Double Buy)"
        elif foreign_sum < 0 and inst_sum < 0:
            sentiment = "BEARISH (Double Sell)"
            
        return {
            "sentiment": sentiment,
            "foreign_3d": foreign_sum,
            "institution_3d": inst_sum,
            "recent_data": recent.to_dict('records')
        }
