import pandas as pd
import japanize_matplotlib # これを追加するだけ
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import numpy as np
from scipy.optimize import curve_fit
import os

# --- 指数関数モデルの定義 ---
def exponential_func(x, a, b, c):
    """指数関数: a * exp(b * x) + c"""
    return a * np.exp(b * x) + c

# --- input()経由でCSVファイルパスを取得する関数 ---
def get_csv_path_from_input():
    """ユーザーにCSVファイルパスの入力を促し、それを返す。"""
    while True:
        file_path = input("解析するCSVファイルのフルパスを入力してください (例: C:\\Users\\YourName\\Documents\\data_file.csv): ")
        if not file_path:
            print("パスが入力されていません。")
            continue
        if not os.path.exists(file_path):
            print(f"エラー: ファイルが見つかりません: {file_path}")
            print("正しいパスを入力してください。")
            retry = input("再入力しますか？ (y/n): ").lower()
            if retry != 'y':
                return None
        elif not file_path.lower().endswith('_esp32_data.csv'):
            print("警告: ファイル名が '_esp32_data.csv' で終わっていません。期待されるファイル形式ですか？")
            confirm = input("このファイルで続行しますか？ (y/n): ").lower()
            if confirm == 'y':
                return file_path
            else:
                print("ファイル選択をキャンセルしました。")
                return None
        else:
            return file_path

# --- メインのプロットおよび解析関数 ---
def plot_and_analyze_data(csv_filepath):
    """
    CSVからデータを読み込み、重量 対 時間の指数関数近似を行い、
    各速度毎の重量中央値を計算・プロットし、その中央値データで指数関数近似を行う。
    """
    try:
        df = pd.read_csv(csv_filepath)
        print(f"Successfully loaded {csv_filepath}")
        print("Columns found:", df.columns.tolist())

        required_cols = ['Timestamp(ESP32)', 'weight', 'speed(rpm)']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(f"Error: Missing required columns: {', '.join(missing_cols)}")
            print(f"Please ensure the CSV contains: {', '.join(required_cols)}")
            return

        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=required_cols, inplace=True)

        if df.empty:
            print("No valid data remaining after cleaning. Cannot proceed.")
            return

        timestamps_esp32 = df['Timestamp(ESP32)'].values
        weights = df['weight'].values
        speeds_rpm = df['speed(rpm)'].values # 全データ点の速度
        time_for_fit = timestamps_esp32 - timestamps_esp32[0]

        # --- 重量 対 時間 の指数関数近似 (これは変更なし) ---
        if len(time_for_fit) > 3 and len(weights) > 3:
            try:
                initial_c = np.mean(weights[-int(len(weights)*0.1):]) if len(weights) >= 10 else np.mean(weights)
                initial_a = weights[0] - initial_c
                if np.isclose(initial_a, 0): initial_a = 1.0 if weights[0] > initial_c else -1.0 if weights[0] < initial_c else 1.0

                initial_b = -1e-5 # Default guess
                if len(weights) > 1 and time_for_fit[-1] > time_for_fit[0]:
                    mid_idx = len(weights) // 2
                    if mid_idx > 0 and not np.isclose(initial_a, 0) and time_for_fit[mid_idx] > 1e-9 :
                        val_for_log_b = (weights[mid_idx] - initial_c) / initial_a
                        if val_for_log_b > 1e-9:
                           initial_b = np.log(val_for_log_b) / time_for_fit[mid_idx]
                           if not np.isfinite(initial_b): initial_b = -1e-5
                        elif (weights[mid_idx] - initial_c) * initial_a < 0:
                            initial_b = 1e-5 if initial_a < 0 else -1e-5
                
                p0_time = [initial_a, initial_b, initial_c]
                params_time, _ = curve_fit(exponential_func, time_for_fit, weights, p0=p0_time, maxfev=20000)
                weight_approximated_vs_time = exponential_func(time_for_fit, *params_time)
                mse_time_fit = np.mean((weights - weight_approximated_vs_time)**2)

                print("\n--- 重量 対 時間 の指数関数近似 ---")
                print(f"式: Weight(t) = a * exp(b * t_offset) + c")
                print(f"近似パラメータ (a, b, c): a = {params_time[0]:.4e}, b = {params_time[1]:.4e}, c = {params_time[2]:.4f}")
                print(f"平均二乗誤差 (MSE): {mse_time_fit:.4f}")
            except RuntimeError:
                print("\n重量 対 時間 の指数関数近似で最適なパラメータを見つけられませんでした。")
            except Exception as e:
                print(f"\n重量 対 時間 のカーブフィット中にエラー発生: {e}")
        else:
            print("\n重量 対 時間 の指数関数近似を行うにはデータ点が不足しています。")

        # --- 各速度(rpm)における重量の中央値を計算 ---
        median_weights_at_speeds = None
        unique_speeds = None
        if 'speed(rpm)' in df.columns and 'weight' in df.columns:
            median_data = df.groupby('speed(rpm)')['weight'].median().sort_index().reset_index()
            if not median_data.empty and len(median_data) > 0:
                unique_speeds = median_data['speed(rpm)'].values
                median_weights_at_speeds = median_data['weight'].values
                print("\n--- 各速度における重量中央値 ---")
                for s_val, mw_val in zip(unique_speeds, median_weights_at_speeds):
                    print(f"Speed: {s_val} rpm, Median Weight: {mw_val:.3f}")
            else:
                print("中央値の計算に必要なデータグループがありません。")
        else:
            print("中央値の計算に必要な'speed(rpm)'または'weight'列がありません。")

        # --- 中央値に基づいた 重量 対 速度(rpm) の指数関数近似 ---
        params_speed_fit_median = None
        mse_speed_fit_median = None
        speed_range_for_median_plot = None
        fitted_median_weights = None

        if unique_speeds is not None and median_weights_at_speeds is not None and len(unique_speeds) > 3:
            # len(unique_speeds) > 3 perché abbiamo 3 parametri (a,b,c) nella funzione esponenziale
            try:
                # unique_speeds è già ordinato grazie a sort_index().values
                guess_c_s_median = np.min(median_weights_at_speeds)
                guess_a_s_median = median_weights_at_speeds[0] - guess_c_s_median
                if np.isclose(guess_a_s_median, 0):
                    guess_a_s_median = np.median(median_weights_at_speeds) - guess_c_s_median
                if np.isclose(guess_a_s_median, 0): guess_a_s_median = 1.0

                if len(median_weights_at_speeds) > 1 and median_weights_at_speeds[-1] > median_weights_at_speeds[0] + 1e-6: # Aggiunta tolleranza
                    guess_b_s_median = 1e-3
                elif len(median_weights_at_speeds) > 1 and median_weights_at_speeds[-1] < median_weights_at_speeds[0] - 1e-6:
                    guess_b_s_median = -1e-3
                else: # Piatto o singolo punto per b
                    guess_b_s_median = 1e-9 if len(median_weights_at_speeds) > 1 else 0.0


                p0_s_median = [guess_a_s_median, guess_b_s_median, guess_c_s_median]
                
                params_s_m, _ = curve_fit(
                    exponential_func,
                    unique_speeds,
                    median_weights_at_speeds,
                    p0=p0_s_median,
                    maxfev=40000 # Aumentato maxfev per dati potenzialmente più difficili (pochi punti)
                )
                params_speed_fit_median = params_s_m
                speed_range_for_median_plot = np.linspace(unique_speeds.min(), unique_speeds.max(), num=200)
                fitted_median_weights = exponential_func(speed_range_for_median_plot, *params_s_m)
                mse_speed_fit_median = np.mean((median_weights_at_speeds - exponential_func(unique_speeds, *params_s_m))**2)

                print("\n--- 中央値に基づいた 重量 対 速度(rpm) の指数関数近似 ---")
                print(f"式: Median_Weight(Speed) = a * exp(b * Speed) + c")
                print(f"近似パラメータ (a, b, c): a = {params_s_m[0]:.4e}, b = {params_s_m[1]:.4e}, c = {params_s_m[2]:.4f}")
                print(f"平均二乗誤差 (MSE, 対中央値): {mse_speed_fit_median:.4f}")

            except RuntimeError:
                print("\n中央値に基づいた 重量 対 速度(rpm) の指数関数近似で最適なパラメータを見つけられませんでした。")
                print("データが指数関数に適合しない、初期推定値の調整が必要、またはユニークな速度点が少なすぎる可能性があります。")
            except Exception as e:
                print(f"\n中央値に基づいた 重量 対 速度(rpm) のカーブフィット中にエラー発生: {e}")
        else:
            if unique_speeds is not None and len(unique_speeds) <= 3:
                print("\n中央値に基づいた指数関数近似を行うには、ユニークな速度のデータ点数が少なすぎます (3点超必要)。")
            elif unique_speeds is None:
                 print("\n中央値データがないため、中央値に基づいた指数関数近似は行えません。")
        
        # --- 重量 対 速度(rpm) のプロット (中央値折れ線と近似曲線付き) ---
        fig_scatter, ax_scatter = plt.subplots(figsize=(12, 8))

        # 1. 全データ点のスキャッタープロット
        ax_scatter.scatter(speeds_rpm, weights, alpha=0.25, label='実測値 (全データ)', color='silver', s=25, zorder=1)

        # 2. 速度毎の重量中央値の折れ線グラフ
        if unique_speeds is not None and median_weights_at_speeds is not None:
            ax_scatter.plot(unique_speeds, median_weights_at_speeds, color='dodgerblue', linestyle='-', linewidth=2.2,
                            marker='o', markersize=7, markerfacecolor='white', markeredgecolor='dodgerblue',
                            label='速度毎の重量中央値', zorder=2)

        # 3. 中央値に基づいた指数近似曲線
        if fitted_median_weights is not None and params_speed_fit_median is not None and speed_range_for_median_plot is not None:
            fit_label_median = (f'指数近似 (中央値ベース)\n'
                                f'a={params_speed_fit_median[0]:.2e}, b={params_speed_fit_median[1]:.2e}, c={params_speed_fit_median[2]:.2f}\n'
                                f'MSE: {mse_speed_fit_median:.2e}')
            ax_scatter.plot(speed_range_for_median_plot, fitted_median_weights, color='crimson', linestyle='--', linewidth=2.5,
                            label=fit_label_median, zorder=3)

        ax_scatter.set_xlabel('Speed (rpm)', fontsize=14)
        ax_scatter.set_ylabel('Weight', fontsize=14)
        ax_scatter.set_title('重量 対 速度(rpm) の解析 (中央値トレンドと近似)', fontsize=18)
        
        ax_scatter.legend(loc='best', fontsize=10, frameon=True, framealpha=0.9)
        ax_scatter.grid(True, linestyle=':', alpha=0.6)

        ax_scatter.tick_params(axis='both', which='major', labelsize=12)
        ax_scatter.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax_scatter.ticklabel_format(style='sci', axis='y', scilimits=(-3,4), useMathText=True) # scilimits調整
        ax_scatter.xaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax_scatter.ticklabel_format(style='sci', axis='x', scilimits=(-3,4), useMathText=True) # scilimits調整
        
        fig_scatter.tight_layout()
        plt.show()

    except FileNotFoundError:
        print(f"エラー: ファイル {csv_filepath} が見つかりませんでした。")
    except pd.errors.EmptyDataError:
        print(f"エラー: ファイル {csv_filepath} は空です。")
    except KeyError as e:
        print(f"エラー: 列 {e} がCSVに見つかりません。CSVのフォーマットを確認してください。")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")

# --- メイン実行ブロック ---
if __name__ == "__main__":
    csv_file_path = get_csv_path_from_input()
    if csv_file_path:
        plot_and_analyze_data(csv_file_path)
    else:
        print("ファイルパスが指定されなかったため、処理を終了します。")