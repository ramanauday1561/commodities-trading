# Studies

Every change to the app's calls is tested first, on history only, with the pass rule written down before the run. This file keeps the results of the finished one-off studies. Their scripts were removed on 29 Oct 2026 to keep the project small; the code comments in `scripts/` that name them (for example "streak_study") refer to the notes below.

To get a removed script back, run `git show cf6df74:scripts/<name>.py > scripts/<name>.py` and add its mode back to `scripts/experiment.py`.

## Still in the project (re-run these before changing a call)

| Script | Experiment mode | What it tests |
|---|---|---|
| `long_signal_study.py` | `longsignal` | The 09:15 signal on ~11 years of overnight history (the main check for any change to it) |
| `history_study.py` | `history` | The 09:15 trade on 5-minute candles: exits, India VIX at the open, event days |
| `preopen_study.py` | `preopen`, `results`, `earnings` | Pre-open inputs, results days |
| `open_study.py` | `open` | Calls traded from the open or 10:15, expiry days |
| `accuracy_study.py` | `accuracy`, `improve`, `extreme`, `strategy`, `commodity` | Where direction calls are reliable (shared helpers for the others) |
| `vix_study.py` | `vix` | India VIX as an input or filter |
| `intraday_rules_study.py` | `intrarules` | Chase / fade / flip intraday rules on 11 years of 5-minute candles |
| `nextcandle_study.py` | `nextcandle` | The next 10-minute candle (also used by the Next 10 min page) |
| `minute_study.py` | `minute` | 1-minute details as inputs for the next 30 / 60 minutes (30 Oct 2026: fails; 53.5% right, still losing after costs in 7 of 10 years) |
| `option_study.py` | `options` (data: `optdata`) | Real NIFTY option prices (30 Oct 2026): the 11-year 09:15 signal loses in options since 2022 (live version +Rs2,093 a lot on 52 trades, not independent); an ATM straddle from the open lost in all 12 years (-Rs674 a lot a day); NIFTY moved 0.84 of what VIX implied |

## Finished studies (scripts removed)

| Study | Date | Question | Outcome |
|---|---|---|---|
| roll_study | 20 Oct | Futures roll adjustment; crude in the NIFTY calls | Roll adjustment adopted (`rolls.py`); crude dropped from the 09:15 signal |
| hourly_study | 21 Oct | Forecasts from 1-hour candles | Lost money after costs; not used |
| review_study | 21 Oct | Gap surprise, failed gaps, banks after results | Not used |
| oct23_study | 23 Oct | ADRs on their own results days, 06:33 cutoff, high oil | Not used |
| results_size_study | 25 Oct | How many heavyweight stocks count as results days | 11 kept (`results_calendar.py`) |
| streak_study | 26 Oct | The last few days' run as an input | 3-day move (`ret3`) adopted in the 09:15 signal |
| exit_study | 26 Oct | Stops and targets for the 09:15 trade | None beat holding; the 0.5% stop is kept as risk control |
| fii_study | 26 Oct | Foreign investors' futures positions | Not adopted (not among the live inputs) |
| pcr_probe, pcr_study | 26 Oct | NIFTY put-call ratio | Data found; earned less in total; not used |
| midday_study | 28 Oct | The 28 Oct "midday recovery" CALL as a rule | Failed (44% won) |
| kaggle_search, dukascopy_probe | 28 Oct | Years of hourly overnight prices | The overnight history came from Dukascopy (`overnight_data.py`), not Kaggle |
| gift_probe, gift_study | 29 Oct | GIFT / SGX Nifty for the 09:15 trade | Explained 78% of the gap in 2017-2023, but no free history since July 2023; now recorded daily (`gift_record.py`) to re-test later |
| trendday_study | 29 Oct | Ride a strong morning to 15:15 | Failed (51% won, about break-even before option decay) |

## Notes from each removed script

### dukascopy_probe

```
Experiment mode "dukaprobe" (28 Oct 2026): can a GitHub runner get years of free hourly history for the 09:15 signal's
overnight inputs? Yahoo keeps only 2 years of hourly candles, so the signal is tested on ~65 trades. Dukascopy's public
datafeed has 1-minute candles for index CFDs, currencies and commodities, one LZMA file per day; this checks which of
our inputs it has and how far back, on a few sample days. Nothing is saved.
```

### exit_study

```
Experiment mode "exits" (26 Oct 2026): stop-loss and take-profit rules for the from-open trade.

The live trade is held from the 09:15 open to the close. Tested on the same walk-forward from-open signal, with
NIFTY's 1-hour candles (high / low) for the path through the day:
  stop X%       exit when NIFTY moves X% against the trade (0.3, 0.5, 0.75, 1.0)
  target Y%     exit when it moves Y% in favour (0.5, 0.75, 1.0, 1.5)
  stop + target (0.5 / 1.0, 0.75 / 1.5, 0.5 / 0.75)
  wider         trading the top 50% most confident days instead of the top 20%, with a 0.5% or 0.75% stop (can a stop
                make the weaker days worth trading?)
Exits fill at the stop / target level; when one candle touches both, the stop is assumed first (the cautious reading).
A stop can be skipped over by a fast move, so stop results are a little optimistic. Costs ~0.03% per trade as before.
Rule fixed before the run: more per trade than the live hold-to-close by at least 0.02% in both halves, and a higher
total. With 13 variants tried, anything that only just passes is likely luck.
```

### fii_study

```
Experiment mode "fii" (26 Oct 2026): do foreign investors' positions help the from-open signal?

26 Oct 2026: reports credited the rally partly to foreign investors (FIIs) buying ~Rs 888 crore of shares on Friday.
NSE publishes no free history of the daily FII / DII cash flows (only the latest day), but it does publish, every day,
each participant group's open positions in index futures and options (fao_participant_oi_<DDMMYYYY>.csv, the
"participant-wise open interest", back to 2016). Tested here, from the previous session's file (known before the open):
  fii_long    FIIs' share of long index-futures positions, long / (long + short): its change on the previous session
              and its level against the past 60 sessions, as two extra inputs
  agree       trade only when the change in fii_long agrees with the side (rising = bullish)
  client      the same two inputs for retail clients (often the other side of FIIs)
Rule fixed before the run (as vix_study): more per trade than the live signal in both halves and in total, and for
the filter, the skipped trades must lose.
```

### gift_probe

```
Experiment mode "giftprobe" (29 Oct 2026): where can years of GIFT Nifty (SGX Nifty before July 2023) prices come
from? GIFT Nifty trades on NSE IX in Gandhinagar almost round the clock (06:30-15:40 and 16:35-02:45 IST), so it
prices the overnight markets before NIFTY opens; the 11-year test (long_signal_study.py) suggests that is why the
from-open signal's edge faded after 2021. Checks Kaggle, Dukascopy, NSE IX and SGX's public historical files; prints
what each has. Nothing is saved.
```

### gift_study

```
Experiment mode "gift" (29 Oct 2026): does GIFT Nifty (SGX Nifty before July 2023) help the trade from the open?

The 11-year test (long_signal_study.py) found the from-open signal's edge gone since 2022, probably because GIFT Nifty
now trades almost round the clock and the 09:15 open already prices the overnight markets. GIFT Nifty's own history
is not free, but Dukascopy's India 50 CFD (INDIDXUSD, overnight_data.py key "india") follows it and trades while NSE
is closed. Hourly, from 2015; the last candle known before 09:10 IST ends at 08:30 IST.
Inputs from it, for day D (NSE's 15:30 IST close on the day before = "prev"):
  gift_gap      India 50 at 08:30 IST vs at prev 15:30: the gap GIFT points to
  gift_night    prev 15:30 -> 06:30 IST (the US session and the night)
  gift_morning  06:30 -> 08:30 IST (Asia's open, before NSE's)
  gap_surprise  NIFTY's actual 09:15 gap minus gift_gap: what the opening auction added or took away
Checks (walk-forward, traded like the live signal: top-20% days, standing aside after results and US news, 0.5% stop
on 5-minute candles, 0.03% costs; LONG = long_signal_study.LONG):
  1. does it trade at night, and how much of the 09:15 gap does gift_gap explain (before / since July 2023)
  2. LONG vs LONG + the GIFT inputs, over all years and since July 2023
  3. the gap surprise alone: trade against it (the open overshot) or with it, when it is 0.15% or more
Rules fixed before the run: the GIFT inputs help if LONG + GIFT earns more per trade than LONG in both halves, more in
total, and makes money since July 2023 (the GIFT era). The surprise rule needs 30+ trades, half won, both halves up.
Data found (29 Oct 2026): no free GIFT Nifty history (Kaggle, NSE IX's site and SGX's tick files have none usable).
Dukascopy's India 50 CFD followed SGX Nifty and stopped when SGX Nifty moved to GIFT City: hourly prices from Dec 2017
to Jun 2023 only (one flat candle a month after that). So the GIFT-era part of the rule cannot be checked.
Result (run 40755746709, 1,373 sessions, Dec 2017 - Jun 2023):
  1. it traded 9 night hours a day (median) and explained 78% of the variation of NIFTY's 09:15 gap (R^2 0.782), against
     62% for our overnight markets: the open does take in what SGX / GIFT Nifty priced overnight
  2. LONG 186 trades, 38% won, +0.068% a trade (+0.115% / +0.022% by half); LONG + GIFT 149 trades, 46% won, +0.173%
     (+0.284% / +0.064%): better in both halves, but both lost money in 2022 and the first half of 2023 (-1.2%, -1.9%)
  3. fading the opening surprise (NIFTY opened 0.15%+ away from where SGX Nifty pointed, trade back towards it):
     648 trades, 46% won, +0.089% (+0.138% / +0.041%), up in 5 of 7 years; fails "half won". Following it lost.
  Fading the plain gap (no SGX price; NIFTY 5-minute history, 2015-2026, 0.5% stop, checked by hand the same day):
     0.15%+ gaps 2,008 trades, 46% won, +0.051%; since Jul 2023 +0.016% and losing in the later half. Not used.
Nothing changes in the app: GIFT Nifty helped in 2018-2021 but no free history exists for the years since, so it
cannot be tested where it matters. Recording a daily GIFT Nifty quote from now on would let it be tested later.
```

### hourly_study

```
Experiment mode "hourly" (21 Oct 2026): can NIFTY's 1-hour candles forecast the next hour, or the rest of the day?

Before building hourly forecasts (2-3 days of work and hourly runs), test whether they would beat "no change".
Hourly bars: ~2 years from Yahoo. At every hourly bar end in the session (10:15 ... 15:15 IST) two targets:
  next_hour     close of the next bar vs now
  rest_of_day   the day's close vs now
Inputs known at that moment: last bar's move, last two bars, move since the open, move since yesterday's close (the gap
included), where the price sits in today's range, the opening gap, yesterday's move, hour of day.
Models, walk-forward by day (each day's model trained only on earlier days, from day 60): ridge (like the live NIFTY
calls) and LightGBM (refit every 20 days); rules: momentum (follow the last bar) and reversal (fade it).
Scored on direction (vs the share of up moves) and on what a trade earns after ~0.03% costs, on all snapshots and on
the 20% most confident ones (cut-off from earlier days), in each half of the test period and by hour.
```

### kaggle_search

```
Experiment mode "kagglesearch" (28 Oct 2026): public Kaggle datasets with years of intraday (hourly or finer) prices
for the 09:15 signal's overnight inputs: US index futures (ES / NQ), Nikkei, KOSPI, Hang Seng, the Indian ADRs (HDB,
IBN, INFY) and USD/INR. Searches Kaggle's public API without a key and lists what it finds; nothing is downloaded.
```

### midday_study

```
Experiment mode "midday" (28 Oct 2026): the "midday recovery" CALL the user traded on 28 Oct, as a fixed rule.

On 28 Oct NIFTY fell 1.1% by 10:15 and was back near yesterday's close by 13:00. A quick look at 11 years of 5-minute
candles at 13:00 that day (so the idea came from looking at the data, not before it) found 121 such days on which
NIFTY rose from 13:00 to the close 61% of the time. The user bought the 22700 CE at 13:17; it fell to near the stop and
was sold at 14:06 for -Rs676. Fixed before this run, on the stored history (intraday_data.py, 2,855 days from 2015):
  recovery CALL   the day's low before 13:00 at least 0.6% below yesterday's close, and NIFTY at 13:00 (the 12:55
                  candle's close) no more than 0.25% below it: buy at 13:00, stop 0.3% below the entry (checked on each
                  candle's low), out at 15:15 (the 15:10 candle's close). This is the trade made on 28 Oct.
  variants        no stop; a 0.5% stop; "back within 0.25%" on both sides (not above +0.25%); the mirror PUT (high at
                  least 0.6% above yesterday's close, back to no more than +0.25%); both together.
Costs 0.03% a trade (futures; an option costs more and decays). Results are NIFTY's move.
Pass rule (the intraday rule studies' rule): at least 20 trades, at least half of them won, and earning after costs in
both halves of the days. Several variants are tried, so a narrow pass would be luck.
Result (28 Oct 2026, 2,854 days, 12 Jan 2015 - 27 Oct 2026): nothing passed.
  recovery CALL (the 28 Oct trade): 121 trades, 44% won, +0.059% a trade after futures costs (+0.019% / +0.085% by
    half), 7 of 12 years up. It fails the "half won" rule: the 0.3% stop is hit on about half the days, including on days
    that end higher (28 Oct came within 6 points of it). About 13 NIFTY points a trade, less than an option's costs.
  no stop 55% won but the first half lost (-0.074%); 0.5% stop also lost in the first half; "back within 0.25%" 87 trades,
  43% won, first half lost; the mirror PUT lost (38% won); both sides 40% won, +0.016%. Not used in the app.
```

### oct23_study

```
Experiment mode "oct23" (23 Oct 2026): three ideas from 23 Oct, tested before any change.

At 06:33 the pre-open call said "down, very strong"; by 08:57 it was "slightly up, no view", mainly because Infosys's
ADR rose 3.8% ahead of Infosys's own results that evening. NIFTY opened +0.24% and fell about 1% from the open.
  A. ADRs on their own company's results: a run-up or reaction in HDFC Bank / ICICI / Infosys around their own results
     is about that stock, not the market. Variants: drop the ADR input on those sessions, or keep only its move in
     excess of the Nasdaq (nq) move.
  B. Earlier cutoff: the same models with overnight inputs up to 06:33 IST instead of 09:10 IST.
  C. High oil: are the calls worse after Brent rose sharply over the past week, and does a 5-day Brent input help?
Every variant: walk-forward (each day's model from earlier days only), close call, gap call and from-open signal,
scored on all days, the top-20% most confident (cut-off from earlier days), after ~0.03% costs, and in both halves.
```

### pcr_probe

```
Experiment mode "pcrprobe" (26 Oct 2026): can a GitHub runner download NSE's daily F&O bhavcopy, the free official
file with every contract's open interest, and compute NIFTY's put-call ratio (open interest of NIFTY index puts over
calls) from it? If so, years of end-of-day PCR can be rebuilt for a backtest.
Two formats: the old one up to 5 Jul 2024 (fo<DDMONYYYY>bhav.csv.zip) and the UDiFF one from 8 Jul 2024.
```

### pcr_study

```
Experiment mode "pcr" (26 Oct 2026): does NIFTY's put-call ratio help the from-open signal?

PCR = open interest of NIFTY index puts / calls at the previous session's close, from NSE's daily F&O bhavcopy
(pcr_probe), so it is known before the 09:15 open. Tested on the from-open signal (top-20% most confident days,
walk-forward, ~0.03% costs):
  input           PCR change on the previous session and its level against the past 60 sessions as two extra inputs
  skip_high_pcr   stand aside when PCR is high (z > 1 against the past 60 sessions)
  skip_low_pcr    stand aside when PCR is low (z < -1)
  skip_pcr_jump   stand aside after PCR moved more than 15% in a session
  agree_bull      trade only when the PCR change agrees with the side, reading a rising PCR as bullish (put writing)
  agree_bear      the same, reading a rising PCR as bearish (put buying)
Rule fixed before the run (as vix_study): more per trade than the live signal in both halves and in total, at least
20 trades, and for a filter the trades it skips lose money. Six variants were tried, so a narrow pass is luck.
```

### results_size_study

```
Experiment mode "resultsize" (25 Oct 2026): how many NIFTY stocks should count as "heavyweight results"?

The from-open signal stands aside on the session after one of the heaviest stocks reports (results_calendar.HEAVY, 11
names). Tested here: the 5, 11, 20 or all 50 heaviest. For each list, the same walk-forward from-open signal (top-20%
most confident days, cut-off from earlier days, ~0.03% costs) trades only on sessions with no result from that list
since the previous session. Reported: the trades kept and what they earned (all, and in both halves), what the skipped
trades would have earned (skipping is only worth it if those lose), how often NIFTY moved more than 1% on flagged vs
other sessions, and which tickers Yahoo could serve dates for.
Rule fixed before the run: switch from 11 only to a list whose kept trades earn more per trade than 11's in both
halves, with a higher total and skipped trades that lose money; otherwise keep 11.
Result (25 Oct 2026, 2023-10-26 to 2026-10-23, 81 trades without any skip): 11 kept. See results_calendar's docstring.
```

### review_study

```
Experiment mode "review" (21 Oct 2026): patterns behind 19 and 21 Oct, tested before any change.

On both days NIFTY opened higher than the overnight markets implied, then sold off all day (19 Oct: +0.02% open,
-1.11% close; 21 Oct: +0.55% open vs a +0.10% gap call, then below yesterday's close by noon). Heavyweight bank results
had just come out (HDFC Bank's ADR -3.3% overnight on 21 Oct), and a very large IPO (Jio Platforms) opened on 21 Oct.
Questions, each scored on ~2 years of hourly data, walk-forward, after ~0.03% costs and in both halves:
  A. gap surprise: when NIFTY opens further than the pre-open gap call said, does the excess fade by the close?
     (trade at the 09:15 open against the surprise; needs a call just after the open)
  B. failed gap: a gap up that is below the open by 10:15 (or a gap down above it) -> follow the failure 10:15 -> close
  C. banks after results: the HDFC Bank / ICICI ADR move on the sessions after their results, as an input to the close
     call and the from-open signal (interaction term), vs the live inputs
```

### roll_study

```
Experiment mode "rolls" (20 Oct 2026): what the futures roll adjustment (rolls.py) changes, and the NIFTY crude input.

crude / gold / silver: LightGBM on Yahoo's raw continuous history vs the roll-adjusted one, on the live backtest days
(same days as predict.py), plus the next-day forecast each one gives against the price trading now.
nifty: the close call, the from-open signal and the gap call with and without the crude input (Yahoo's hourly CL=F also
jumps at every roll, e.g. 18 Sep and 15 Oct 2026, and its weight in the calls is close to zero).
```

### streak_study

```
Experiment mode "streak" (26 Oct 2026): does the last few days' run help the from-open signal?

26 Oct 2026: NIFTY had lost 2.36% over four sessions, opened lower on Infosys and rallied 1.6% from the low ("bargain
buying after a four-day fall"). The signal only knows the previous day's move (prev_day). Tested, with closes known
before the open: the 3-day and 5-day move to the previous close, and the number of down (or up) closes in a row
(negative for down), as extra inputs to the from-open signal (top-20% most confident days, walk-forward, ~0.03% costs).
Also reported: the average open-to-close move after 3+ down closes in a row vs other days.
Rule fixed before the run (as vix_study): more per trade than the live signal in both halves and in total.
```

### trendday_study

```
Experiment mode "trendday" (29 Oct 2026): can a strong morning be ridden to 15:15 with a CALL (or a PUT)?

Asked after 29 Oct 2026: NIFTY opened flat (22,690.65), was +0.5% by 10:15 with India VIX easing and Bank NIFTY along,
and closed +1.05%. "Follow the move" made Rs12,425 that day but has lost in every year since 2015, so this tests the
narrow version that day suggests, on the stored 5-minute history (intraday_data.py: NIFTY, Bank NIFTY, India VIX).
Rule, fixed before the run:
  at 10:15 (the close of the 10:10 candle) NIFTY is 0.4% or more above its 09:15 open, Bank NIFTY is too, and India VIX
  is below yesterday's close -> buy at 10:15 and hold to 15:15 (the close of the 15:10 candle). The mirror (0.4% or more
  below, Bank NIFTY too, VIX above yesterday) is a PUT. Run with no stop, and with the 0.5% stop the app uses
  (checked on 5-minute highs and lows from 10:15).
Money: NIFTY % after 0.03% costs (as the 09:15 signal is tested), and an at-the-money option as in
  nextcandle_study.py: half the NIFTY move minus about 1.85 option points (Rs120 a lot) a round trip. Five hours of
  time decay is not included, so the option figures are better than real.
Passes only if, for the rule as written (0.4%, both sides): 100+ trades, half or more won, and it earns after costs in
  both halves of the years, in 7 or more of the 12 years, and since July 2023 (the GIFT Nifty era).
  0.3% and 0.6% and each side alone are printed beside it, to see how fragile it is, not to pick the best.
Result (29 Oct 2026, run in the session on the intraday-data branch: 2,857 sessions, Jan 2015 - 29 Oct 2026): fails.
  On 29 Oct it fired (10:15: NIFTY +0.42% from the open, Bank NIFTY +0.62%, VIX -2.2%): CALL +0.64% to 15:15.
  Over 11 years, no stop: 381 trades, 51% won, -0.001% a trade (about -Rs28 a lot before time decay), 6 of 12 years up,
    -0.015% since July 2023. CALL only +0.11% since July 2023 but on 29 trades, -0.09% in the first half.
  With the 0.5% stop: 45% won (fails "half won"), +0.02% a trade, about +1.2 option points (+Rs80 a lot) before time
    decay, 7 of 12 years, +0.037% since July 2023. Five hours of decay on an at-the-money weekly option is several
    points, more than that edge.
  0.3% and 0.6% land in the same place (+0.02% to +0.07% a trade); nothing is far enough from zero to pay for an option.
  So 29 Oct was a day the rule wins, not a rule: strong mornings carry on to 15:15 about as often as they fade.
```
