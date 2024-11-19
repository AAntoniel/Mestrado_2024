import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import (
    mean_squared_error,
    r2_score,
    mean_absolute_percentage_error,
    mean_absolute_error,
)
from sklearn.model_selection import train_test_split
import sys

import tensorflow as tf
from keras import backend as K

from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Reshape
from tensorflow.keras.layers import LSTM

from bayes_opt import BayesianOptimization

import math
import os
import datetime

from memory_profiler import profile
from pympler import muppy, summary, tracker, asizeof
import gc

# import tracemalloc

# tracemalloc.start()


# def print_mem_usage():
#     current, peak = tracemalloc.get_traced_memory()
#     print(
#         f"Memória atual usada: {current / 1024 / 1024:.2f} MiB; Pico de memória: {peak / 1024 / 1024:.2f} MiB"
#     )


class SlidingWindow:
    #   Vai instânciar a classe e vai necessitar da definição do tamanho das amostras
    def __init__(self, n_samples, trainw, testw):
        self.n_samples = n_samples
        self.trainw = trainw
        self.testw = testw

        self.n_splits = math.ceil((self.n_samples - self.trainw) / testw)

        #       Faz uma verificação e aponta um erro caso as condições não sejam atendidas
        assert n_samples != self.trainw
        assert self.testw > 0

    #   Realiza as divisões para os conjuntos
    def split(self, X, y=None, groups=None):
        #       Gera duas sequências de dados, indo de treino ao final, com o passo de teste
        for i, k in enumerate(range(self.trainw, self.n_samples, self.testw)):

            #           Faz a separação dos dados
            trainidxs = slice(k - self.trainw, k)
            testidxs = slice(k, k + self.testw)

            #           ????
            if i + 1 == self.n_splits:
                testidxs = slice(k, self.n_samples)

            yield trainidxs, testidxs

            if i + 1 == self.n_splits:
                break

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits


#   Classe similimar a Sliding Window, mudando somente a divisão dos dados
class ExpandingWindow:
    def __init__(self, n_samples, trainw, testw):
        self.n_samples = n_samples
        self.trainw = trainw
        self.testw = testw

        self.n_splits = math.ceil((self.n_samples - self.trainw) / testw)

        assert n_samples != self.trainw
        assert self.testw > 0

    def split(self, X, y=None, groups=None):
        for i, k in enumerate(range(self.trainw, self.n_samples, self.testw)):
            #           k provavelmente é o conjunto de treinamento, 365 ou 730
            trainidxs = slice(0, k)
            testidxs = slice(k, k + self.testw)

            if i + 1 == self.n_splits:
                testidxs = slice(k, self.n_samples)

            yield trainidxs, testidxs

            if i + 1 == self.n_splits:
                break

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits


df = pd.read_csv("C:/Users/Antoniel/Desktop/Mestrado/data/dataset.csv")
df = df.dropna()
df["timestamp"] = pd.to_datetime(df["timestamp"])
df.set_index("timestamp", inplace=True)

# Separa as features e o target
target = df.iloc[:, 0].T
features = df.iloc[:, 1:]

# Normaliza as features e o target separadamente
scaler_features = MinMaxScaler(feature_range=(0, 1))
scaled_features = scaler_features.fit_transform(features)

scaler_target = MinMaxScaler(feature_range=(0, 1))
scaled_target = scaler_target.fit_transform(target.values.reshape(-1, 1))

# # X_train - features de 2016 até 2018
# # X_test - features de 2019
# # y_train - dados históricos de 2016 até 2018
# # y_test - dados históricos de 2019
# Divide em conjuntos de treino e teste
X_train, X_test, y_train, y_test = train_test_split(
    scaled_features, scaled_target, test_size=0.25, shuffle=False
)

# Obter a data e hora atuais
current_time = datetime.datetime.now()

# Formatar a data e hora no formato desejado
timestamp = current_time.strftime("%Y-%m-%d-%H-%M-%S")

# Criação de um diretório, se não exisistir
output_dir = "output"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

metrics_file = os.path.join(output_dir, f"metrics-LSTM_{timestamp}.csv")

with open(metrics_file, "w") as f:
    f.write("model,units,epochs,bs,dropout,rmse,mae,mape,r2,split\n")

# CSV com ytrue e yhat
output_dir2 = "output_ytrue_yhat"
if not os.path.exists(output_dir2):
    os.makedirs(output_dir2)

values_file = os.path.join(output_dir2, f"results_lstm-{timestamp}.csv")

with open(values_file, "w") as f:
    f.write("model,ytrue,yhat\n")  # Cabeçalho do CSV

# Dir com LSTM análises
output_dir3 = "LSTM_analysis"
if not os.path.exists(output_dir3):
    os.makedirs(output_dir3)

metrics_file2 = os.path.join(output_dir3, f"all_metrics-lstm_{timestamp}.csv")
with open(metrics_file2, "w") as f:
    f.write(
        "model,units,epochs,bs,dropout,rmse,rmse_std,mae,mae_std,mape,mape_std,r2,split\n"
    )

results_csv_dir = os.path.join(output_dir3, "results_csv")
if not os.path.exists(results_csv_dir):
    os.makedirs(results_csv_dir)


metrics_list = []

# ----------------------------------------------------------------------------------------------------------------
# -------------------------------------------- LSTM SW1Y VALIDATION --------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------

# Definindo o intervalo de busca para os hiperparâmetros
batch_size_options = [128]
pbounds = {
    "units": (50, 150),
    "epochs": (2, 2),  # Definindo a faixa para units
    "batch_size": (0, len(batch_size_options) - 1),  # Faixa para batch  size
    "dropout": (0.0, 0.1),  # Faixa para dropout
}

metrics_params_sw1y = dict(
    best_rmse=float("inf"),
    best_mae=[],
    best_mape=[],
    best_r2=[],
    best_epochs=[],
    best_unit=[],
    best_batch=[],
    best_dropout=[],
)

# mem_tracker = tracker.SummaryTracker()
# print("Uso de memória antes do treinamento:")
# mem_tracker.print_diff()


@profile
# Função objetivo que será usada na otimização bayesiana
def treinar_modelo(units, epochs, batch_size, dropout):
    units = int(units)  # O bayes opt retorna floats, é necessário converter para int
    epochs = int(epochs)
    batch_size = batch_size_options[int(batch_size)]

    # Inicializando as variáveis de resultados
    results_sw1y_val = dict(ytrue=[], yhat=[])
    scoring_sw1y_val = dict(rmse=[], mae=[], mape=[], r2=[])

    SW1Y_val = SlidingWindow(
        n_samples=len(df.loc["2017-01-01":"2018-12-31"]),
        trainw=len(df.loc["2017-01-01":"2017-12-31"]),
        testw=7,
    )

    # Loop para Expanding Window
    for i, (trainidxs, testidxs) in enumerate(SW1Y_val.split(df)):
        K.clear_session()
        gc.collect()
        X = X_train[365:][trainidxs]
        y = y_train[365:][trainidxs]

        # Dados de validação
        X_t = X_train[365:][testidxs]
        y_t = y_train[365:][testidxs]

        X = X.reshape((X.shape[0], 1, X.shape[1]))
        X_t = X_t.reshape((X_t.shape[0], 1, X_t.shape[1]))
        y = y.reshape((y.shape[0], 1))

        # Definindo o modelo LSTM
        model = Sequential(
            [
                LSTM(
                    units,
                    dropout=dropout,
                    input_shape=(X.shape[1], X.shape[2]),
                ),
                Dense(1),
            ]
        )

        model.compile(optimizer="adam", loss="mse")
        model.fit(X, y, epochs=epochs, batch_size=batch_size, verbose=0, shuffle=False)

        # print("Uso de memória após o treinamento:")
        # mem_tracker.print_diff()

        print(units, dropout, batch_size)

        # Previsão
        predictions = model.predict(X_t)
        yhat = scaler_target.inverse_transform(predictions)
        ytrue = scaler_target.inverse_transform(y_t)

        results_sw1y_val["ytrue"].append(ytrue)
        results_sw1y_val["yhat"].append(yhat)

        del model

    ytrue_val_sw1y = []
    yhat_val_sw1y = []

    # Concatena os resultados
    for i in range(len(results_sw1y_val["ytrue"])):
        ytrue_val_sw1y.extend(results_sw1y_val["ytrue"][i])
        yhat_val_sw1y.extend(results_sw1y_val["yhat"][i])

    print("Tamanho de yhat_val_sw1y", len(yhat_val_sw1y))
    print("Tamanho de ytrue_val_sw1y", len(ytrue_val_sw1y))

    ytrue_val = np.array(ytrue_val_sw1y)
    yhat_val = np.array(yhat_val_sw1y)
    print("Tamanho de yhat_val", len(yhat_val))
    print("Tamanho de ytrue_val", len(ytrue_val))

    for i in range(len(results_sw1y_val["ytrue"]) - 1):
        # Define o número de dias para esta iteração
        if i == 51:
            num_days = 8
        else:
            num_days = 7

        # Calcula os índices para os últimos dias
        start_idx = i * 7
        end_idx = start_idx + num_days

        # Obtém os últimos 7 ou 8 elementos de ytrue e yhat
        ytrue_last = ytrue_val[start_idx:end_idx]
        yhat_last = yhat_val[start_idx:end_idx]

        # Calcula as métricas para os últimos dias
        rmse = mean_squared_error(ytrue_last, yhat_last, squared=False)
        mae = mean_absolute_error(ytrue_last, yhat_last)
        mape = mean_absolute_percentage_error(ytrue_last, yhat_last)
        r2 = r2_score(ytrue_last, yhat_last)

        # Adiciona as métricas ao dicionário de pontuação
        scoring_sw1y_val["rmse"].append(rmse)
        scoring_sw1y_val["mae"].append(mae)
        scoring_sw1y_val["mape"].append(mape)
        scoring_sw1y_val["r2"].append(r2)

    rmse_mean = round(np.mean(scoring_sw1y_val["rmse"]), 2)
    rmse_std = round(np.std(scoring_sw1y_val["rmse"]), 2)
    mae_mean = round(np.mean(scoring_sw1y_val["mae"]), 2)
    mae_std = round(np.std(scoring_sw1y_val["mae"]), 2)
    mape_mean = round((np.mean(scoring_sw1y_val["mape"]) * 100), 2)
    mape_std = round((np.std(scoring_sw1y_val["mape"]) * 100), 2)
    r2_mean = round(np.mean(scoring_sw1y_val["r2"]), 2)

    if rmse_mean < metrics_params_sw1y["best_rmse"]:
        metrics_params_sw1y["best_rmse"] = rmse_mean
        metrics_params_sw1y["best_mae"] = mae_mean
        metrics_params_sw1y["best_mape"] = mape_mean
        metrics_params_sw1y["best_r2"] = r2_mean
        metrics_params_sw1y["best_epochs"] = epochs
        metrics_params_sw1y["best_unit"] = units
        metrics_params_sw1y["best_batch"] = batch_size
        metrics_params_sw1y["best_dropout"] = dropout

    print(
        metrics_params_sw1y["best_rmse"],
    )

    # Write validation metrics to CSV file
    with open(metrics_file2, "a") as f:
        f.write(
            f"LSTM-SW1Y,{units},{epochs},{batch_size},{dropout},{rmse_mean},{rmse_std},{mae_mean},{mae_std},{mape_mean},{mape_std},{r2_mean},val\n"
        )

    ytrue_yhat_df = pd.DataFrame(
        {"ytrue": ytrue_val.flatten(), "yhat": yhat_val.flatten()}
    )
    ytrue_yhat_df.to_csv(
        os.path.join(
            results_csv_dir,
            f"LSTM-SW1Y_{units}_{epochs}_{batch_size}_{dropout}_{timestamp}.csv",
        ),
        index=False,
    )

    memory_tracker = tracker.SummaryTracker()
    memory_tracker.print_diff()

    return -rmse_mean  # Minimização


# Otimizador Bayesiano
optimizer = BayesianOptimization(
    f=treinar_modelo,
    pbounds=pbounds,
    random_state=42,
)

# Executar a otimização
optimizer.maximize(
    init_points=2,  # Número de amostras aleatórias para iniciar
    n_iter=2,  # Número de iterações da otimização
)

with open(metrics_file, "a") as f:
    f.write(
        "LSTM-SW1Y,{},{},{},{},{},{},{},{},val\n".format(
            metrics_params_sw1y["best_unit"],
            metrics_params_sw1y["best_epochs"],
            metrics_params_sw1y["best_batch"],
            metrics_params_sw1y["best_dropout"],
            metrics_params_sw1y["best_rmse"],
            metrics_params_sw1y["best_mae"],
            metrics_params_sw1y["best_mape"],
            metrics_params_sw1y["best_r2"],
        )
    )

# Melhor resultado
print("-" * 20)
print("Best_Params_SW1Y_Val:")
for key, value in metrics_params_sw1y.items():
    print(f"{key}: {value}")
print(optimizer.max)

# ----------------------------------------------------------------------------------------------------------------
# -------------------------------------------- LSTM SW1Y TEST --------------------------------------------------------
# ----------------------------------------------------------------------------------------------------------------

SW1Y_test = SlidingWindow(
    n_samples=len(df.loc["2018-01-01":"2019-12-31"]),
    trainw=len(df.loc["2018-01-01":"2018-12-31"]),
    testw=7,
)

results_sw1y_test = dict(ytrue=[], yhat=[])
scoring_sw1y_test = dict(rmse=[], mae=[], mape=[], r2=[])

for i, (trainidxs, testidxs) in enumerate(SW1Y_test.split(df)):
    X = scaled_features[730:][trainidxs]
    y = scaled_target[730:][trainidxs]

    # Dados de teste
    X_t = scaled_features[730:][testidxs]
    y_t = scaled_target[730:][testidxs]

    X = X.reshape((X.shape[0], 1, X.shape[1]))
    X_t = X_t.reshape((X_t.shape[0], 1, X_t.shape[1]))
    y = y.reshape((y.shape[0], 1))

    # Definição do modelo LSTM
    model = Sequential(
        [
            LSTM(
                metrics_params_sw1y["best_unit"],
                dropout=metrics_params_sw1y["best_dropout"],
                input_shape=(X.shape[1], X.shape[2]),
            ),
            Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse")

    # Treinamento do modelo
    model.fit(
        X,
        y,
        epochs=metrics_params_sw1y["best_epochs"],
        batch_size=metrics_params_sw1y["best_batch"],
        verbose=0,
        shuffle=False,
    )

    print(
        "Parametros atuais para teste SW1Y: ",
        metrics_params_sw1y["best_unit"],
        metrics_params_sw1y["best_epochs"],
        metrics_params_sw1y["best_batch"],
        metrics_params_sw1y["best_dropout"],
    )

    # Previsões para os dados de teste
    predictions = model.predict(X_t)

    yhat = scaler_target.inverse_transform(predictions)
    ytrue = scaler_target.inverse_transform(y_t)

    results_sw1y_test["ytrue"].append(ytrue)
    results_sw1y_test["yhat"].append(yhat)

ytrue_test_values = []
yhat_test_values = []

# Percorre os resultados e concatena os valores de cada array
for i in range(len(results_sw1y_test["ytrue"])):
    ytrue_test_values.extend(results_sw1y_test["ytrue"][i])
    yhat_test_values.extend(results_sw1y_test["yhat"][i])

# Converte as listas para arrays numpy
ytrue_test = np.array(ytrue_test_values)
yhat_test = np.array(yhat_test_values)

for i in range(len(results_sw1y_test["ytrue"]) - 1):
    # Define o número de dias para esta iteração
    if i == 51:
        num_days = 8
    else:
        num_days = 7

    # Calcula os índices para os últimos dias
    start_idx = i * 7
    end_idx = start_idx + num_days

    # Obtém os últimos 7 ou 8 elementos de ytrue e yhat
    ytrue_last = ytrue_test[start_idx:end_idx]
    yhat_last = yhat_test[start_idx:end_idx]

    # Calcula as métricas para os últimos dias
    rmse = mean_squared_error(ytrue_last, yhat_last, squared=False)
    mae = mean_absolute_error(ytrue_last, yhat_last)
    mape = mean_absolute_percentage_error(ytrue_last, yhat_last)
    r2 = r2_score(ytrue_last, yhat_last)

    # Adiciona as métricas ao dicionário de pontuação
    scoring_sw1y_test["rmse"].append(rmse)
    scoring_sw1y_test["mae"].append(mae)
    scoring_sw1y_test["mape"].append(mape)
    scoring_sw1y_test["r2"].append(r2)

rmse_mean = round(np.mean(scoring_sw1y_test["rmse"]), 2)
mae_mean = round(np.mean(scoring_sw1y_test["mae"]), 2)
mape_mean = round((np.mean(scoring_sw1y_test["mape"]) * 100), 2)
r2_mean = round(np.mean(scoring_sw1y_test["r2"]), 2)

# Write test metrics to CSV file
with open(metrics_file, "a") as f:
    f.write(
        f"LSTM-SW1Y,{metrics_params_sw1y['best_unit']},{metrics_params_sw1y['best_epochs']},{metrics_params_sw1y['best_batch']},{metrics_params_sw1y['best_dropout']},{rmse_mean},{mae_mean},{mape_mean},{r2_mean},test\n"
    )

# Iterar sobre os resultados das janelas de teste
for i in range(len(results_sw1y_test["ytrue"])):
    ytrue = results_sw1y_test["ytrue"][i]
    yhat = results_sw1y_test["yhat"][i]

    # Escrever os valores reais e previstos em uma linha do arquivo CSV
    with open(values_file, "a") as f:
        for true, pred in zip(ytrue, yhat):
            f.write(f"LSTM-SW1Y,{true},{pred}\n")


print("-" * 20)

print("RMSE_SW1Y_Test:", rmse_mean)
print("MAE_SW1Y_Test:", mae_mean)
print("MAPE_SW1Y_Test:", mape_mean)
print("R2_SW1Y_Test:", r2_mean)


# # ----------------------------------------------------------------------------------------------------------------
# # -------------------------------------------- LSTM SW1Y VALIDATION ------------------------------------------------
# # ----------------------------------------------------------------------------------------------------------------

# SW1Y_val = SlidingWindow(
#     n_samples=len(df.loc["2017-01-01":"2018-12-31"]),
#     trainw=len(df.loc["2017-01-01":"2017-12-31"]),
#     testw=7,
# )

# best_rmse_SW1Y_val = float("inf")
# best_params_SW1Y = None
# best_r2_SW1Y_val = None
# best_mae_SW1Y_val = None
# best_mape_SW1Y_val = None

# for units, epochs, batch_size, optimizer, dense, verbose, dropout in param_combinations:
#     resultsSW1Y_val = dict(ytrue=[], yhat=[])
#     scoringSW1Y_val = dict(rmse=[], mae=[], mape=[], r2=[])

#     # Loop para Sliding Window
#     for i, (trainidxs, testidxs) in enumerate(SW1Y_val.split(df)):
#         X = X_train[365:][trainidxs]
#         y = y_train[365:][trainidxs]

#         # Dados de validação
#         X_t = X_train[365:][testidxs]
#         y_t = y_train[365:][testidxs]

#         X = X.reshape((X.shape[0], 1, X.shape[1]))
#         X_t = X_t.reshape((X_t.shape[0], 1, X_t.shape[1]))

#         # Definição do modelo LSTM
#         model = Sequential(
#             [
#                 LSTM(units, dropout=dropout, input_shape=(X.shape[1], X.shape[2])),
#                 Dense(dense),
#             ]
#         )
#         model.compile(optimizer=optimizer, loss="mse")

#         # Treinamento do modelo
#         model.fit(
#             X, y, epochs=epochs, batch_size=batch_size, verbose=verbose, shuffle=False
#         )

#         # print("Len X_train", len(X))
#         # # print("X_train", X_train)
#         # print("Len X_test", len(y))
#         # print("X_test", X_test)
#         print(
#             "Parametros atuais de SW1Y: ",
#             units,
#             epochs,
#             batch_size,
#             optimizer,
#             dense,
#             dropout,
#         )

#         # Previsões para os dados de validação
#         predictions = model.predict(X_t)

#         yhat = scaler_target.inverse_transform(predictions)
#         ytrue = scaler_target.inverse_transform(y_t)

#         resultsSW1Y_val["ytrue"].append(ytrue)
#         resultsSW1Y_val["yhat"].append(yhat)

#     ytrue_val_SW1Y = []
#     yhat_val_SW1Y = []

#     for i in range(len(resultsSW1Y_val["ytrue"])):
#         ytrue_val_SW1Y.extend(resultsSW1Y_val["ytrue"][i])
#         yhat_val_SW1Y.extend(resultsSW1Y_val["yhat"][i])

#     # Converte as listas para arrays numpy
#     ytrue_val = np.array(ytrue_val_SW1Y)
#     yhat_val = np.array(yhat_val_SW1Y)

#     for i in range(len(resultsSW1Y_val["ytrue"]) - 1):
#         # Define o número de dias para esta iteração
#         if i == 51:
#             num_days = 8
#         else:
#             num_days = 7

#         # Calcula os índices para os últimos dias
#         start_idx = i * 7
#         end_idx = start_idx + num_days

#         # Obtém os últimos 7 ou 8 elementos de ytrue e yhat
#         ytrue_last = ytrue_val[start_idx:end_idx]
#         yhat_last = yhat_val[start_idx:end_idx]

#         # Calcula as métricas para os últimos dias
#         rmse = mean_squared_error(ytrue_last, yhat_last, squared=False)
#         mae = mean_absolute_error(ytrue_last, yhat_last)
#         mape = mean_absolute_percentage_error(ytrue_last, yhat_last)
#         r2 = r2_score(ytrue_last, yhat_last)

#         # Adiciona as métricas ao dicionário de pontuação
#         scoringSW1Y_val["rmse"].append(rmse)
#         scoringSW1Y_val["mae"].append(mae)
#         scoringSW1Y_val["mape"].append(mape)
#         scoringSW1Y_val["r2"].append(r2)

#     # print("predictions_2018_EW", predictions_2018_EW)
#     # print("predictions_2018_EW len", len(predictions_2018_EW))
#     # validation_target = validation[:, 0]
#     rmse_mean = round(np.mean(scoringSW1Y_val["rmse"]), 2)
#     mae_mean = round(np.mean(scoringSW1Y_val["mae"]), 2)
#     mape_mean = round((np.mean(scoringSW1Y_val["mape"]) * 100), 2)
#     r2_mean = round(np.mean(scoringSW1Y_val["r2"]), 2)

#     if rmse_mean < best_rmse_SW1Y_val:
#         best_rmse_SW1Y_val = rmse_mean
#         best_mae_SW1Y_val = mae_mean
#         best_mape_SW1Y_val = mape_mean
#         best_r2_SW1Y_val = r2_mean
#         best_unit_SW1Y = units
#         best_epochs_SW1Y = epochs
#         best_batch_size_SW1Y = batch_size
#         best_optimizer_SW1Y = optimizer
#         best_dense_SW1Y = dense
#         best_verbose_SW1Y = verbose
#         best_dropout_SW1Y = dropout

# # Write validation metrics to CSV file
# with open(metrics_file, "a") as f:
#     f.write(
#         f"LSTM-SW1Y,{best_unit_SW1Y},{best_epochs_SW1Y},{best_batch_size_SW1Y},{best_optimizer_SW1Y},{best_dense_SW1Y},{best_verbose_SW1Y},{best_dropout_SW1Y},{best_rmse_SW1Y_val},{best_mae_SW1Y_val},{best_mape_SW1Y_val},{best_r2_SW1Y_val},val\n"
#     )

# print("-" * 20)
# print(
#     "Best_Params_SW1Y_Val",
#     best_unit_SW1Y,
#     best_epochs_SW1Y,
#     best_batch_size_SW1Y,
#     best_optimizer_SW1Y,
#     best_dense_SW1Y,
#     best_verbose_SW1Y,
#     best_dropout_SW1Y,
# )
# print("Best_RMSE_SW1Y_Val : ", best_rmse_SW1Y_val)
# print("Best_R2_SW1Y_Val:", best_r2_SW1Y_val)
# print("Best_MAE_SW1Y_Val:", best_mae_SW1Y_val)
# print("Best_MAPE_SW1Y_Val:", best_mape_SW1Y_val)

# # ----------------------------------------------------------------------------------------------------------------
# # -------------------------------------------- LSTM SW1Y TEST ------------------------------------------------------
# # ----------------------------------------------------------------------------------------------------------------

# SW1Y_test = SlidingWindow(
#     n_samples=len(df.loc["2018-01-01":"2019-12-31"]),
#     trainw=len(df.loc["2018-01-01":"2018-12-31"]),
#     testw=7,
# )

# resultsSW1Y_test = dict(ytrue=[], yhat=[])
# scoringSW1Y = dict(rmse=[], mae=[], mape=[], r2=[])

# for i, (trainidxs, testidxs) in enumerate(SW1Y_test.split(df)):
#     X = scaled_features[730:][trainidxs]
#     y = scaled_target[730:][trainidxs]

#     # Dados de teste
#     X_t = scaled_features[730:][testidxs]
#     y_t = scaled_target[730:][testidxs]

#     X = X.reshape((X.shape[0], 1, X.shape[1]))
#     X_t = X_t.reshape((X_t.shape[0], 1, X_t.shape[1]))

#     # Definição do modelo LSTM
#     model = Sequential(
#         [
#             LSTM(best_unit_SW1Y, dropout=best_dropout_SW1Y, input_shape=(X.shape[1], X.shape[2])),
#             Dense(best_dense_SW1Y),
#         ]
#     )
#     model.compile(optimizer=best_optimizer_SW1Y, loss="mse")

#     # Treinamento do modelo
#     model.fit(
#         X,
#         y,
#         epochs=best_epochs_SW1Y,
#         batch_size=best_batch_size_SW1Y,
#         verbose=best_verbose_SW1Y,
#         shuffle=False,
#     )

#     print(
#         "Parametros atuais para teste SW1Y: ",
#         best_unit_SW1Y,
#         best_epochs_SW1Y,
#         best_batch_size_SW1Y,
#         best_optimizer_SW1Y,
#         best_dense_SW1Y,
#         best_dropout_SW1Y,
#     )

#     # Previsões para os dados de teste
#     predictions = model.predict(X_t)

#     yhat = scaler_target.inverse_transform(predictions)
#     ytrue = scaler_target.inverse_transform(y_t)

#     resultsSW1Y_test["ytrue"].append(ytrue)
#     resultsSW1Y_test["yhat"].append(yhat)

# ytrue_test_SW1Y = []
# yhat_test_SW1Y = []

# # Percorre os resultados e concatena os valores de cada array
# for i in range(len(resultsSW1Y_test["ytrue"])):
#     ytrue_test_SW1Y.extend(resultsSW1Y_test["ytrue"][i])
#     yhat_test_SW1Y.extend(resultsSW1Y_test["yhat"][i])

# # Converte as listas para arrays numpy
# ytrue_test = np.array(ytrue_test_SW1Y)
# yhat_test = np.array(yhat_test_SW1Y)

# for i in range(len(resultsSW1Y_test["ytrue"]) - 1):
#     # Define o número de dias para esta iteração
#     if i == 51:
#         num_days = 8
#     else:
#         num_days = 7

#     # Calcula os índices para os últimos dias
#     start_idx = i * 7
#     end_idx = start_idx + num_days

#     # Obtém os últimos 7 ou 8 elementos de ytrue e yhat
#     ytrue_last = ytrue_test[start_idx:end_idx]
#     yhat_last = yhat_test[start_idx:end_idx]

#     # Calcula as métricas para os últimos dias
#     rmse = mean_squared_error(ytrue_last, yhat_last, squared=False)
#     mae = mean_absolute_error(ytrue_last, yhat_last)
#     mape = mean_absolute_percentage_error(ytrue_last, yhat_last)
#     r2 = r2_score(ytrue_last, yhat_last)

#     # Adiciona as métricas ao dicionário de pontuação
#     scoringSW1Y["rmse"].append(rmse)
#     scoringSW1Y["mae"].append(mae)
#     scoringSW1Y["mape"].append(mape)
#     scoringSW1Y["r2"].append(r2)

# rmse_mean = round(np.mean(scoringSW1Y["rmse"]), 2)
# mae_mean = round(np.mean(scoringSW1Y["mae"]), 2)
# mape_mean = round((np.mean(scoringSW1Y["mape"]) * 100), 2)
# r2_mean = round(np.mean(scoringSW1Y["r2"]), 2)

# # Write test metrics to CSV file
# with open(metrics_file, "a") as f:
#     f.write(
#         f"LSTM-SW1Y,{best_unit_SW1Y},{best_epochs_SW1Y},{best_batch_size_SW1Y},{best_optimizer_SW1Y},{best_dense_SW1Y},{best_verbose_SW1Y},{best_dropout_SW1Y},{rmse_mean},{mae_mean},{mape_mean},{r2_mean},test\n"
#     )

# # Iterar sobre os resultados das janelas de teste
# for i in range(len(resultsSW1Y_test["ytrue"])):
#     ytrue = resultsSW1Y_test["ytrue"][i]
#     yhat = resultsSW1Y_test["yhat"][i]

#     # Escrever os valores reais e previstos em uma linha do arquivo CSV
#     with open(values_file, "a") as f:
#         for true, pred in zip(ytrue, yhat):
#             f.write(f"LSTM-SW1Y,{true},{pred}\n")

# print("-" * 20)

# print("RMSE_SW1Y_Test:", rmse_mean)
# print("MAE_SW1Y_Test:", mae_mean)
# print("MAPE_SW1Y_Test:", mape_mean)
# print("R2_SW1Y_Test:", r2_mean)


# --------------------
# Best_Params_SW2Y_Val 200 20 32 1
# Best_RMSE_SW2Y_Val :  2121.7115645950275
# Best_R2_SW2Y_Val: 0.6316805460701567
# Best_MAE_SW2Y_Val: 1589.2042177193166
# Best_MAPE_SW2Y_Val: 0.1260106807398723
# --------------------
# RMSE_SW2Y_Test :  2367.647767442117
# R2_SW2Y_Test: 0.5871888756482156
# MAE_SW2Y_Test: 1791.926024240453
# MAPE_SW2Y_Test: 0.14183656790857965
# --------------------
# Best_Params_SW1Y_Val 300 30 32 1
# Best_RMSE_SW1Y_Val :  2241.8750171595943
# Best_R2_SW1Y_Val: 0.5887794916231792
# Best_MAE_SW1Y_Val: 1664.9277825804147
# Best_MAPE_SW1Y_Val: 0.1303451402703845
# --------------------
# RMSE_SW1Y_Test :  2506.6348696170994
# R2_SW1Y_Test: 0.537300149610946
# MAE_SW1Y_Test: 1937.713805196243
# MAPE_SW1Y_Test: 0.15114201066445354
