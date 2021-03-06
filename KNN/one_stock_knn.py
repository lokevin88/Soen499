import os
import numpy as np
import pandas as pd
# Spark imports
from pyspark.rdd import RDD
from pyspark.sql import DataFrame
from pyspark.sql import SparkSession
from pyspark.sql import Window
from pyspark.sql.types import *
from pyspark.sql.functions import *

from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.model_selection import GridSearchCV
from sklearn.model_selection import cross_val_score
from sklearn import metrics
from indicator import generate_indicator
import matplotlib.pyplot as matplot
import matplotlib.dates as mdates
import matplotlib.ticker as ticker

'''
HELPER FUNCTIONS

These functions are here to help you. Instructions will tell you when
you should use them. Don't modify them!
'''

# Useful functions to print RDDs and Dataframes.
def toCSVLineRDD(rdd):
    '''
    This function convert an RDD or a DataFrame into a CSV string
    '''
    a = rdd.map(lambda row: ",".join([str(elt) for elt in row])) \
        .reduce(lambda x, y: os.linesep.join([x, y]))
    return a + os.linesep


def toCSVLine(data):
    '''
    Convert an RDD or a DataFrame into a CSV string
    '''
    if isinstance(data, RDD):
        return toCSVLineRDD(data)
    elif isinstance(data, DataFrame):
        return toCSVLineRDD(data.rdd)
    return None

# Initialize a spark session.
def init_spark():
    spark = SparkSession \
        .builder \
        .appName("Python Spark SQL basic example") \
        .config("spark.some.config.option", "some-value") \
        .getOrCreate()
    return spark

def knn(stock_code, showDataVisualization):

    spark = init_spark()

    generate_indicator(stock_code)
    indicator_data = 'sp500_indicator/'+stock_code+'_indicator.csv'
    data_frame = spark.read.csv(indicator_data, header=True, mode="DROPMALFORMED")
    data_frame = data_frame.replace("inf", None).na.drop()
    # data_frame.show()

    '''
    calculate label column:
    if stock close price increase 5% compare to 5days ago, label should be 1 which mean buy
    if stock close price oscillate less than 5% compare to 5days ago, label should be 0 which mean hold
    if stock close price decrease 5% compare to 5days ago, label should be -1 which mean sell
    '''


    def precentage(new_data, old_data):
        ''' (current close price - shirft close price(5 days))*100/ shirft close price  '''
        pg = (new_data - old_data) / old_data * 100
        return pg


    # def comp_prev(column_close, column_lag):
    #     print(column_close.value)
    #     print(column_lag)
    #     if (precentage(column_close, column_lag) >= 5):
    #         return 1
    #     elif (precentage(column_close, column_lag) <= -5):
    #         return -1
    #     else:
    #         return 0

    ''' 
            date|close|  lag|
    +----------+-----+-----+
    |2013-02-08|33.05| null|
    |2013-02-11|33.26| null|
    |2013-02-12|33.74| null|
    |2013-02-13|33.55| null|
    |2013-02-14|33.27| null|
    type: <class 'pandas.core.frame.DataFrame'>
    
    Use pyspark window, lead, and lag function:
    Ref: https://riptutorial.com/apache-spark/example/22861/window-functions---sort--lead--lag---rank---trend-analysis
    '''
    new_df = data_frame.withColumn('lag', lag('close', 5).over(Window.orderBy(asc('date'))))
    # new_df.show()

    '''
    How to use pyspark dataframe do if else
    ref:https://stackoverflow.com/questions/39048229/spark-equivalent-of-if-then-else
    
    date|close|  lag| label
    +----------+-----+-----+
    2013-02-22|32.59|33.27|    0|
    |2013-02-25|32.07|33.98|   -1|
    |2013-02-26|32.04|33.84|   -1|

    '''

    new_df = new_df.withColumn('label',
                               when(col('lag').isNull(), 0).when(precentage(col('close'), col('lag')) <= -2, -1).when(
                                   precentage(col('close'), col('lag')) >= 2, 1).otherwise(0))

    # new_df.show()

    '''Change pyspark dataframe to pandas dataframe'''
    new_df = new_df.toPandas()

    '''KNN start'''
    # TODO One bug is If the input is default all columns: Input contains NaN, infinity or a value too large for dtype('float64')
    # I think some columns value is too big

    '''
    type: <class 'pandas.core.frame.DataFrame'>
    '''
    x = new_df[
        ['date', 'volume', 'macd', 'macds', 'macdh', 'rsi_14', 'boll', 'boll_ub', 'boll_lb', 'kdjk', 'kdjd',
         'kdjj', 'adx', 'close_5_ema', 'close_10_ema', 'close_20_ema', 'close_40_ema','vr']]  # drop columns here

    # reset index to date
    x = x.set_index('date').astype(float)
    # print(type(x))
    # print(x.head())

    # Extracted date column
    date = new_df[['date']]  #.sort_values(by='date')

    '''Scale the dataset to 0-1'''
    min_max_scaler = MinMaxScaler()  # normalization, a lot of choice from sklearn
    x_scale = min_max_scaler.fit_transform(x)
    x = pd.DataFrame(x_scale)
    # print(x.head())
    # print(x.shape)

    # add date to the normalized data
    x = x.join(date)
    x = x.set_index('date').astype(float)
    # print(x.head())

    y = new_df['label'].values
    # print(y)
    # print(y.shape)

    # Using the normal K Nearest Neighbors Classifier
    accuracy, f1 = useKNeighborsClassifier(x, y, stock_code, showDataVisualization)

    # Using K Fold Cross Validation
    accuracyK, f1K = useKFold(x, y, stock_code, showDataVisualization)

    # Using the Grid Search Cross Validation to determine the best n_neighbors value
    # accuracy, f1 = useKnnGridSearch(x, y, stock_code, showDataVisualization)


    # Using the manual method to find the best K value
    # accuracy, f1 = useKnnWithBestK(x, y, stock_code, showDataVisualization)

    return (accuracy, f1, accuracyK, f1K)

def useKNeighborsClassifier(x, y, stock_code, showDataVisualization):
    # Split dataset to training and testing
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, train_size=0.8, random_state=42,
                                                        stratify=y)
    # n_neighbors is the parameter for K values
    knn = KNeighborsClassifier(n_neighbors=5, metric='euclidean', p=2)
    knn.fit(x_train, y_train)

    y_pred = knn.predict(x_test)
    # print(y_pred)

    # To see the index values, which is the dates
    # print("xtest: " + str(x_test.index.sort_values()))

    # To get the size of each training and testing sets
    # print("xtrain" + str(len(x_train)))
    # print("ytrain" + str(len(y_train)))
    # print("xtest" + str(len(x_test)))
    # print("ytest" + str(len(y_test)))
    # print("ypred" + str(len(y_pred)))


    # Calculate accuracy and f1
    accuracy = metrics.accuracy_score(y_test, y_pred)
    f1 = metrics.f1_score(y_test, y_pred, average='weighted')
    print(stock_code+": Accuracy:", accuracy)
    print(stock_code+": F1_score:", f1)

    # if(showDataVisualization):
    #     drawGraph(stock_code, x_test, y_test, y_pred)

    return accuracy, f1

# Reference: https://kevinzakka.github.io/2016/07/13/k-nearest-neighbor/
def useKFold(x, y, stock_code, showDataVisualization):
    # Split dataset to training and testing
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, train_size=0.8, random_state=42,
                                                        stratify=y)
    kBest = 0
    scoreBest = 0
    knnBest = KNeighborsClassifier()
    allK = []
    allScores = []
    for kValue in range(1, 50):
        knn = KNeighborsClassifier(n_neighbors=kValue, metric='euclidean', p=2)
        scoreA = cross_val_score(knn, x_train, y_train, cv=10, scoring="accuracy")
        averageScoreA = scoreA.mean()
        allK.append(kValue)
        allScores.append(averageScoreA)
        if(averageScoreA > scoreBest):
            kBest = kValue
            scoreBest = averageScoreA
            knnBest = knn

    # print("K: "+str(kBest) + " | Score: "+str(scoreBest))

    knnBest.fit(x_train, y_train)

    y_pred = knnBest.predict(x_test)
    # print(x_test.index)
    writePredictions(stock_code, x_test.index, y_pred)

    # Calculate accuracy and f1
    accuracy = metrics.accuracy_score(y_test, y_pred)
    f1 = metrics.f1_score(y_test, y_pred, average='weighted')
    # score = knn.score(x_test, y_test)
    print(stock_code+": K-Fold - Accuracy:", accuracy)
    print(stock_code+": K-Fold - F1_score:", f1)
    # print(stock_code+": Score:", score)

    if(showDataVisualization):
        drawGraph(stock_code, x_test, y_test, y_pred)
        drawGraphForKValues(stock_code, allK, allScores)

    return accuracy, f1

def drawGraph(stock_code, x_test, y_test, y_pred):
    # Used Matplotlib to show the difference between test and prediction on a graph
    sortedDates = x_test.index.sort_values()
    matplot.scatter(sortedDates, y_test, color="red")
    matplot.scatter(sortedDates, y_pred, color="green")
    matplot.title("Prediction for " + stock_code)
    matplot.xlabel("Date")
    matplot.ylabel("Value")
    labels = ['']*len(sortedDates)
    labels[::40] = [date for date in sortedDates[::40]]
    matplot.gca().xaxis.set_major_formatter(ticker.FixedFormatter(labels))
    matplot.gcf().autofmt_xdate()
    matplot.show()

def drawGraphForKValues(stock_code, k, scores):
    # Used Matplotlib to show the difference between test and prediction on a graph
    matplot.plot(k, scores)
    matplot.title("Best N Neighbor value for " + stock_code)
    matplot.xlabel("K Value")
    matplot.ylabel("Cross-Validation Score")
    matplot.show()


def writePredictions(stock, dates, predictions):
    df = pd.DataFrame(list(zip(dates, predictions)), columns = ['Date', 'Prediction'])
    # print(df)
    sortedDf = df.sort_values(by='Date')
    sortedDf.to_csv('sp500_predictions/'+stock+'.csv', index=False, header=True)

