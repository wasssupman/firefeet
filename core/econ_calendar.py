import requests
import pandas as pd
import yaml
import datetime
import os
from datetime import timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import re

class EconCalendar:
    """
    Economic Calendar Scraper & Analyzer
    Fetches major economic events from MarketWatch.
    """
    
    BASE_URL = "https://www.marketwatch.com/economy-politics/calendar"
    
    def __init__(self, config_path="config/econ_calendar.yaml"):
        self.config = self._load_config(config_path)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _load_config(self, path):
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            print(f"[EconCalendar] Config load failed: {e}")
        return {"indicators": []}

    def fetch_all(self):
        """
        Fetch economic calendar data from MarketWatch.
        """
        try:
            session = requests.Session()
            r = session.get(self.BASE_URL, headers=self.headers, timeout=10)
            r.raise_for_status()
            return self._parse_marketwatch_html(r.text)
        except Exception as e:
            print(f"[EconCalendar] Fetch failed: {e}")
            return []

    def _parse_marketwatch_html(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        events = []
        
        table = soup.find('table')
        if not table:
            return []
            
        current_date_str = ""
        year = datetime.date.today().year
        
        # Regex for date headers like "MONDAY, FEB. 9"
        date_pattern = re.compile(r"(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)", re.I)

        rows = table.find_all('tr')
        for row in rows:
            # 1. Day Header detection
            # It can be in ethier th class="day" or a td with text containing a day name
            header_cell = row.find(['th', 'td'], class_='day')
            if not header_cell:
                # Secondary check: single cell with bold text or just day name
                cells = row.find_all(['td', 'th'])
                if len(cells) == 1 and date_pattern.search(cells[0].text):
                    header_cell = cells[0]
                elif len(cells) > 0 and date_pattern.search(cells[0].text) and len(cells[0].text) < 30:
                    # Sometimes the date is in the first cell of a longer row but acts as a divider
                    # However, in MW standard it is usually a row with 1 cell or class='day'
                    if 'am' not in cells[0].text.lower() and 'pm' not in cells[0].text.lower():
                        header_cell = cells[0]

            if header_cell:
                try:
                    raw_text = header_cell.text.strip().upper()
                    # MONDAY, FEB. 9 -> FEB 9 2026
                    clean_text = raw_text.replace('.', '').replace(',', '')
                    parts = clean_text.split()
                    if len(parts) >= 3:
                        month_str = parts[1][:3] # FEB
                        day_val = parts[2]
                        dt = datetime.datetime.strptime(f"{month_str} {day_val} {year}", "%b %d %Y")
                        current_date_str = dt.strftime("%Y-%m-%d")
                except (ValueError, IndexError):
                    pass
                continue

            if not current_date_str:
                continue

            # 2. Data Row
            cols = row.find_all('td')
            # MarketWatch: Time (ET), Report, Period, Actual, Forecast, Previous
            if len(cols) >= 5:
                time_val = cols[0].text.strip()
                event_name = cols[1].text.strip()
                actual = cols[3].text.strip()
                forecast = cols[4].text.strip()
                
                if not event_name or 'None scheduled' in event_name:
                    continue

                # Filter by config
                is_target = False
                target_name = ""
                importance = "low"
                country = "US"
                
                unit = "pct"
                for indicator in self.config.get('indicators', []):
                    for kw in indicator.get('keywords', []):
                        if kw.lower() in event_name.lower():
                            is_target = True
                            target_name = indicator['name']
                            importance = indicator.get('importance', 'low')
                            country = indicator.get('country', 'US')
                            unit = indicator.get('unit', 'pct')
                            break
                    if is_target:
                        break
                
                if not is_target:
                    continue

                # ET to KST (+14h)
                kst_time = "-"
                if time_val and (':' in time_val or 'am' in time_val.lower() or 'pm' in time_val.lower()):
                    try:
                        # "8:30 am" or "10:50 am"
                        t_clean = time_val.lower().replace(' ', '')
                        et_naive = datetime.datetime.strptime(f"{current_date_str} {t_clean}", "%Y-%m-%d %I:%M%p")
                        # DST 자동 대응: zoneinfo로 ET→KST 변환
                        et_tz = ZoneInfo("America/New_York")
                        kst_tz = ZoneInfo("Asia/Seoul")
                        et_dt = et_naive.replace(tzinfo=et_tz)
                        kst_dt = et_dt.astimezone(kst_tz)
                        kst_time = kst_dt.strftime("%H:%M (KST)")
                    except (ValueError, KeyError):
                        pass

                events.append({
                    "date": current_date_str,
                    "time": time_val,
                    "kst_time": kst_time,
                    "name": event_name,
                    "target_name": target_name,
                    "country": country,
                    "importance": importance,
                    "unit": unit,
                    "actual": actual if actual and actual != '-' else '-',
                    "forecast": forecast if forecast and forecast != '-' else '-',
                })
        
        return events

    def analyze_reaction(self, event_name):
        from core.news_scraper import NewsScraper
        results = {"news": []}
        try:
            scraper = NewsScraper()
            news_items = scraper.search_news(event_name)
            results["news"] = [n['title'] for n in news_items[:2]]
        except Exception as e:
            print(f"[EconCalendar] 뉴스 반응 분석 실패 ({event_name}): {e}")
        return results

    def generate_report_section(self):
        lines = ["## 📅 주요 경제 지표 일정\n"]
        
        all_events = self.fetch_all()
        
        # Today in local system (KST typically or wherever the bot runs)
        today = datetime.date.today().strftime("%Y-%m-%d")
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        target_dates = [today, tomorrow]
        
        data_set = [e for e in all_events if e['date'] in target_dates]
        
        if not data_set:
            lines.append("오늘과 내일 예정된 주요 지표 일정이 없습니다.")
            return "\n".join(lines)

        # Deduplication
        final_events = []
        seen = set()
        for e in data_set:
            key = (e['name'], e['date'], e['time'])
            if key not in seen:
                final_events.append(e)
                seen.add(key)

        # Grouping
        grouped_events = {}
        for e in final_events:
            t_name = e['target_name']
            if t_name not in grouped_events:
                grouped_events[t_name] = {
                    "importance": e['importance'],
                    "country": e['country'],
                    "events": []
                }
            grouped_events[t_name]["events"].append(e)

        # Build Sections
        sorted_groups = sorted(grouped_events.items(), 
                              key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x[1]['importance'], 3))
        
        released_section = []
        upcoming_section = []

        for name, data in sorted_groups:
            importance_tag = f"[{data['importance'].upper()}]"
            country_tag = f"[{data['country']}]"
            data['events'].sort(key=lambda x: (x['date'], x['time']))

            g_released = [ev for ev in data['events'] if ev['actual'] and ev['actual'] != '-']
            g_upcoming = [ev for ev in data['events'] if not ev['actual'] or ev['actual'] == '-']

            if g_released:
                released_section.append(f"### {importance_tag} {country_tag} {name}")
                for ev in g_released:
                    display_name = ev['name'] if ev['name'] != name else ""
                    suffix = f" ({display_name})" if display_name else ""
                    forecast_info = f" / 예상 {ev['forecast']} (Source: MarketWatch)" if ev['forecast'] != '-' else ""
                    time_disp = f"{ev['time']} ET | {ev['kst_time']}" if ev['kst_time'] != "-" else ev['time']
                    released_section.append(f"- **{ev['date']} {time_disp}**{suffix}: 실제 **{ev['actual']}**{forecast_info}")
                    
                    try:
                        analysis = self.analyze_reaction(name)
                        if analysis["news"]:
                            released_section.append(f"  > 📰 관련 뉴스: {analysis['news'][0]}")
                    except Exception as e:
                        print(f"[EconCalendar] 반응 분석 실패 ({name}): {e}")
                released_section.append("")

            if g_upcoming:
                upcoming_section.append(f"### {importance_tag} {country_tag} {name}")
                for ev in g_upcoming:
                    display_name = ev['name'] if ev['name'] != name else ""
                    suffix = f" ({display_name})" if display_name else ""
                    forecast_info = f"예상: {ev['forecast']} (Source: MarketWatch)" if ev['forecast'] != '-' else "예상: 미정"
                    time_disp = f"{ev['time']} ET | {ev['kst_time']}" if ev['kst_time'] != "-" else ev['time']
                    upcoming_section.append(f"- **{ev['date']} {time_disp}**{suffix}: {forecast_info}")
                upcoming_section.append("")

        if released_section:
            lines.append("### ✅ 발표 결과")
            lines.extend(released_section)
        if upcoming_section:
            lines.append("### ⏳ 향후 일정")
            lines.extend(upcoming_section)
            
        return "\n".join(lines)

if __name__ == "__main__":
    ec = EconCalendar()
    print(ec.generate_report_section())
