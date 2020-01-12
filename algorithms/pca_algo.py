"""
Based on paper by Avellaneda and Lee.
Long-short based on PCA-derived risk factors.
author: Nathan Mugerwa

To improve: Try different learning models, de-"black box" the PCA process and try
different factor derivation processes (i.e. etfs), **create a more intelligent model,
and more!
----------------------------------------------------------------------------------------
Key Errors:

I. MODEL DOES NOT ACCOUNT FOR TAIL EVENTS (Remember 2008?)
It does not check WHY a stock's idiosyncratic residual is so high. For example, a 
stock that announces bankruptcy and drops by 99% in a day would be treated as extremely 
cheap and bought up by this algorithm.

II. MODEL MAKES VERY STRONG ASSUMPTIONS
Returns fluctuation is a stationary process, mean-reverting, ... My time as
a discretionary trader makes me confident in eliminating lots of these assumptions
in different iterations of the algorithm. Too theoretical.

III. MODEL PERFORMS BADLY OUT-OF-SAMPLE
Bootstrapping? Hmm... Needs more thought.
"""

import quantopian.algorithm as algo
from quantopian.pipeline import Pipeline
from quantopian.pipeline.data.builtin import USEquityPricing
from quantopian.pipeline.filters import QTradableStocksUS
import numpy as np
from sklearn import linear_model
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

#######################################################

LOOKBACK = 256
N_COMPONENTS = 5

def initialize(context):
    # Expected fixed costs of strategy.
    set_slippage(slippage.FixedBasisPointsSlippage(basis_points=0.0, volume_limit=1.0))
    set_commission(commission.PerShare(cost=0.00, min_trade_cost=0.00))
    
    print ("lookback days: %s, PCA: %s" %(LOOKBACK, N_COMPONENTS))

    # Schedules portfolio re-construction.
    algo.schedule_function(
        trade,
        algo.date_rules.every_day(),
        algo.time_rules.market_open(hours=0, minutes=1),
    )

    # Our "pipeline" masks the entire universe of stocks, selecting some subset to apply our ranking system to.
    algo.attach_pipeline(make_pipeline(), 'pipeline')
    
def make_pipeline():
    base_universe = QTradableStocksUS()

    # We use the entire universe; daily candles.
    pipe = Pipeline(
        screen=base_universe,
        columns={
            'open': USEquityPricing.open.latest,
        }
    )
   
    return pipe

# Initialization routine.
def before_trading_start(context, data):
    context.output = algo.pipeline_output('pipeline')
    context.security_list = context.output.index
       
def derive_factors(price_data):
    rets = np.log(price_data).diff()[1:]
    rets.dropna(inplace=True, axis=1) # remove stocks with incomplete histories.
        
    stocks = rets.columns
    
    # Creates normalization operator, applies model to data: data has unit variance and mean = 0.
    # Necessary for PCA accuracy.
    rets = StandardScaler().fit_transform(rets)
    
    # Creates PCA operator, applies to return data. We whiten to ensure independent factors (PCs) downstream.
    pca = PCA(n_components=N_COMPONENTS, whiten=True)
    pca_rets = pca.fit_transform(rets)
    return rets, pca_rets, stocks

def construct_portfolio(context, longs, shorts):
    for p in context.portfolio.positions:
        if context.portfolio.positions[p].amount > 0 and p in shorts:
            order_target_percent(p, -0.01)            
        elif context.portfolio.positions[p].amount < 0 and p in longs:
            order_target_percent(p, 0.01)
        elif context.portfolio.positions[p].amount > 0 and p in longs:
            pass
        elif context.portfolio.positions[p].amount < 0 and p in shorts:
            pass
        elif context.portfolio.positions[p].amount != 0:
            order_target_percent(p, 0.00)
      
    for l in longs:
        if context.portfolio.positions[l].amount == 0:
            order_target_percent(l, 0.01)
    
    for s in shorts:
        if context.portfolio.positions[s].amount == 0:
            order_target_percent(s, -0.01)
    
def trade(context, data):
    '''
    The actual trading algorithm: constructs a portfolio as follows:
    1. Derives a PCA model and projects the original return data into the PCA domain (the factor-normalized domain)
    2. Computes residuals of the actual projected returns with predicted returns
    3. Selects the cheapest k/2 stocks and richest k/2 stocks for shorting and longing, respectively.
    4. Constructs the portfolio according to balancing scheme.
    
    Improvements: Try different learning models, lots more!
    '''
    prices = data.history(context.security_list, fields='price', bar_count=LOOKBACK, frequency="1d")

    rets, pca_rets, stocks = derive_factors(prices)
    
    X_train = pca_rets[:-1,:]
    X_test = pca_rets[-1:,:]
    
    df = pd.DataFrame(rets, columns=stocks)
    df = df[1:]
        
    predictions = []
    
    # Linear regression on the idiosyncratic returns. Goal is to rate deviation of actual idiosyncratic
    # to predicted (what our mean-reverting model expects).
    for stock in stocks:
        y = df[stock]
        m = linear_model.LinearRegression()
        m.fit(X_train, y)        
        pred = m.predict(X_test)[0]
        # Scoring: R^2; how well the model predicted the actual returns.
        score = m.score(X_train, y)

        predictions.append({'stock':stock, 'pred': pred, 'score': score})
        
    df = pd.DataFrame(predictions)
  
    # Extremely simple selection: If portolio size = k, we short top k/2 and sell bottom k/2.
    df.sort_values('pred', ascending=False, inplace=True)
    longs = df[:100]
    shorts = df[-100:]
    
    longs.sort_values('score', ascending=False, inplace=True)
    longs = longs['stock'][:25].tolist() # best scores
    
    shorts.sort_values('score', ascending=False, inplace=True)
    shorts = shorts['stock'][:25].tolist() # best scores
    
    construct_portfolio(context, longs, shorts)
    