import random
import serial
import serial.tools.list_ports
import time
import csv
import os
import datetime
import matplotlib.pyplot as plt
import threading
from matplotlib.animation import FuncAnimation
from matplotlib.ticker import ScalarFormatter

OUT_VOL=0.0007
HX711_AVDD=4.2987
LOAD=500.0
HX711_PGA=128

HX711_SCALE=OUT_VOL * HX711_AVDD / LOAD *HX711_PGA
HX711_ADC1bit=HX711_AVDD/16777216
class DataCollector:
    def __init__(self, port='COM3', baudrate=115200, timeout=1):
        self.ser = serial.Serial(port, baudrate, timeout=timeout)
        time.sleep(1)
        # シリアル通信の受信バッファをクリア
        self.ser.read_all()
        self.script_directory = os.path.dirname(__file__)
        self.timestamps = []
        self.weights = []
        self.speeds = []

    def get_non_negative_integer_input(self, prompt):
        """ 0以上の整数値を入力させる """
        while True:
            try:
                value = int(input(prompt))
                if value < 0:
                    raise ValueError("負数は入力できません。")
                return value
            except ValueError as e:
                print(e)  # エラーメッセージを表示
                print("正しい形式で入力してください。再度入力してください。")

    def show_and_save_settings(self):
        # 入力された値を出力
        print("入力された値:")
        print("開始時のrpm:", self.initial_rpm)
        print("終了時のrpm:", self.final_rpm)
        print("途中での速度変更回数:", self.planned_steps)
        print("実行時間:", self.operation_during)

        self.raw_csv_writer.writerow([0, f"settings:"])
        self.raw_csv_writer.writerow([0, f"initial_rpm: {self.initial_rpm}"])
        self.raw_csv_writer.writerow([0, f"final_rpm: {self.final_rpm}"])
        self.raw_csv_writer.writerow([0, f"planned_steps: {self.planned_steps}"])
        self.raw_csv_writer.writerow([0, f"operation_during: {self.operation_during}"])

    def create_csv_file(self, directory, file_name):
        """
        指定されたディレクトリにCSVファイルを作成し、csv.writerのインスタンスを返す。
        
        Parameters:
            directory (str): CSVファイルを保存するディレクトリのパス。
            file_name (str): 作成するCSVファイルの名前。
        """
        # 指定されたディレクトリが存在しない場合は作成する
        if not os.path.exists(directory):
            os.makedirs(directory)
        
        # 指定されたディレクトリにファイルを保存
        file_path = os.path.join(directory, file_name)
        
        # CSVファイルを作成する
        file_obj = open(file_path, "w", newline='')
        csv_writer = csv.writer(file_obj)
        
        # csv.writerのインスタンスを返す
        return csv_writer, file_obj

    def send_command(self, command):
        self.ser.write(command.encode())

    def set_motor_speed(self, count):
        """
        モーターの速度を設定する関数
        
        Parameters:
            initial_rpm (int): 開始時のrpm。
            one_step_increase (float): 1ステップごとの速度増加量。
            count (int): 現在のステップ数。
        
        Returns:
            int: モーターの遅延時間。
        """
        rpm = self.initial_rpm + self.one_step_increase * count
        motor_delay =round( 60 / (rpm * 200) * 1000000) if rpm != 0 else 0
        self.send_command(f"set_speed {motor_delay}\n")
        
        return motor_delay
    
    def process_response(self, current_ut, response):
        """
        ESP32からの応答を処理し、CSVファイルに書き込む関数
        """
        if response:
            print("Response from ESP32:", response)
            
            # 全てのログ用のCSVファイルへの書き込み
            self.raw_csv_writer.writerow([current_ut, response])
            
            # データのみを抽出して書き込むCSVファイルへの書き込み
            if b"[data]" in response.encode('utf-8'):
                data = response.split(',')
                timestamp_esp32 = int(data[1])
                weight = -int(data[2])*HX711_ADC1bit/HX711_SCALE-140
                speed_delay = int(data[3])
                speed_rpm = 60 / (speed_delay / 1000000 * 200) if speed_delay != 0 else 0
                self.data_csv_writer.writerow([current_ut, timestamp_esp32, weight, speed_delay, speed_rpm])

                self.timestamps.append(timestamp_esp32)
                self.weights.append(weight)
                self.speeds.append(speed_rpm)

    def receive_and_process(self):
        start_ut = time.perf_counter()
        self.send_command("start_output\n")
        self.send_command("set_speed 0\n")
        for count in range(self.planned_steps + 1):
            # 新しい速度を設定
            self.set_motor_speed(count)

            while True:
                # ESP32からの応答を受信
                # シリアル通信のラインにノイズが乗ったりすると変なバイト列が生成されてしまい、エンコードに失敗することがあるので、
                # replaceもしくはignoreを使って回避すべき
                response = self.ser.readline().decode('utf-8', 'ignore').rstrip()

                self.current_ut = time.perf_counter()
                elapsed_ut = self.current_ut - start_ut

                # 応答をCSVファイルに保存し、グラフ描画用データを更新
                self.process_response(self.current_ut, response)

                if elapsed_ut > self.one_step_duration * (count + 1):
                    break

        
        self.send_command("set_speed 0\n")
        self.raw_csv_writer.writerow([time.perf_counter(), "Program finished succesfully."])
        # print("Program finished successfully. Resuming when you close the graph window.")
        print("正常に終了しました。グラフウィンドウを閉じると再開します。")
        # すべてのグラフを削除
        plt.close()
        

    def plot_graph(self):
        """
        2軸グラフを描画する関数
        
        Parameters:
            timestamps (list): タイムスタンプのリスト。
            weights (list): 重量のリスト。
            speeds (list): 速度のリスト。
        """
        fig, ax1 = plt.subplots()

        color = 'tab:red'
        ax1.set_xlabel('Timestamp')
        ax1.set_ylabel('Weight', color=color)
        line1, = ax1.plot([], [], color=color)
        ax1.tick_params(axis='y', labelcolor=color)
        ax1.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))

        ax2 = ax1.twinx()  
        color = 'tab:blue'
        ax2.set_ylabel('Speed (rpm)', color=color)
        line2, = ax2.plot([], [], color=color)
        ax2.tick_params(axis='y', labelcolor=color)

        def update(frame):
            line1.set_data(self.timestamps, self.weights)
            line2.set_data(self.timestamps, self.speeds)
            line1.set_data(self.timestamps, self.weights)
            line2.set_data(self.timestamps, self.speeds)
            ax1.relim()
            ax2.relim()
            ax1.autoscale_view()
            ax2.autoscale_view()
            return line1, line2

        ani = FuncAnimation(fig, update, frames=1, interval=100)
        plt.show()

    def plot_graph_and_save(self, save_path, dpi=300):
        """
        2軸グラフを描画して保存するメソッド
        
        Parameters:
            save_path (str): 保存先のファイルパス。
        """
        fig, ax1 = plt.subplots()

        color = 'tab:red'
        ax1.set_xlabel('Timestamp')
        ax1.set_ylabel('Weight', color=color)
        line1, = ax1.plot(self.timestamps, self.weights, color=color)
        ax1.tick_params(axis='y', labelcolor=color)

        ax2 = ax1.twinx()  
        color = 'tab:blue'
        ax2.set_ylabel('Speed (rpm)', color=color)
        line2, = ax2.plot(self.timestamps, self.speeds, color=color)
        ax2.tick_params(axis='y', labelcolor=color)

        plt.savefig(save_path, format="png", dpi=dpi)
        print("Graph image saved:", save_path)

    def start(self):
        self.start_ut = 0
        self.current_ut = 0
        self.elapsed_ut = 0

        self.initial_rpm = self.get_non_negative_integer_input("開始時のrpmを入力してください: ")
        self.final_rpm = self.get_non_negative_integer_input("終了時のrpmを入力してください: ")
        self.planned_steps = self.get_non_negative_integer_input("途中で何回速度を変更しますか？: ")
        self.operation_during = self.get_non_negative_integer_input("何秒間実行しますか？: ")

        # 顔文字のリスト
        faces = ['(⊙ω⊙)', '(ノ◕ヮ◕)ノ⋇:・ﾟ✧', '(⁄◕ヮ◕)⁄', '(◠‿◠✿)', '(ノ^∇^)', '(˶‾᷄ ⁻̫ ‾᷅˵)', '(^◡^ )', '(✿｡✿)', '(◡‿◡❀)', '(´｡• ᵕ •｡`)', '♪(๑ᴖ◡ᴖ๑)♪', '(≧◡≦)', '(⁄  ⁄^-^(^ ^⋇)⁄', '( ̄▽ ̄)ノ', '(⋇˘︶˘⋇).｡⋇♡', '（＾ｖ＾）', '(✧ω✧)', '(◡‿◡✿)', '( ´ ∀ ` )', '（⋇＾3＾）⁄～♡', '(⋇´▽`⋇)', '(⋇≧▽≦)', '(￣3￣)♡', '(°▽°)', '(●´ω｀●)', '٩(ó｡ò۶ ♡)))♬', 'ヽ(⟩∀⟨☆)ノ', '（⋇＾3＾)⁄～☆', '(o^▽^o)', '(๑˃̵ᴗ˂̵)و', '(｡◕‿◕｡)', '＼(￣▽￣)／', '(≧▽≦)', '╰(°▽°)╯', '(≧ω≦)', '(⋇⌒∇⌒⋇)', '(⋇⟩ω⟨)', '(⊙o⊙)', '(●´⌓`●)', '(⋇°∀°)=3', '(⋇ ˘ ³˘)zZ♡', '(✿ ♥‿♥)', '(˘▽˘⟩ԅ( ˘⌣˘)', '(¬‿¬)', '(⊙_◎)', '(⌐■_■)', '(╹◡╹)', 'ヽ(⋇⌒▽⌒⋇)ﾉ', '(◠‿◠)', '（  ̆ 3 ̆)♡', 'ヽ(＾Д＾)ﾉ', '(◕‿◕✿)', '(⁄ ⁄•⁄ω⁄•⁄ ⁄)', 'ಥ‿ಥ', '(つ✧ω✧)つ', '(｡^‿^｡)', '(๑⟩ᴗ⟨๑)', '(●•̀ㅂ•́)و✧', '(◕‿◕)♡', '( ˘ ³˘)♥', '(•ө•)♡', '(⋇≧ω≦)', '(｡♥‿♥｡)', '( ̄▽ ̄)σ', '(♡ ⟩ω⟨ ♡)', '(⋇^▽^⋇)', '(´ ▽ ` )', '(´｡• ω •｡`)', '(╯✧▽✧)╯', '⁽⁽ଘ( ˊᵕˋ )ଓ⁾⁾', '(⁄• •∖∖)', '(◕‿◕)', '(´ ´｡• ω •｡`) ♡', '(⑅˃◡˂⑅)', '｡^‿^｡', '(▰˘◡˘▰)', '(★^O^★)', '(✪‿✪)ノ', '(￣▽￣)ノ', '(´• ω •`)', '╰( ･ ᗜ ･ )╯', '(°◡°♡).｡', '(⊙ヮ⊙)', '(⺣◡⺣)♡⋇', '(●´ϖ`●)', '(⋇¯︶¯⋇)', '(´∩｡• ᵕ •｡∩`)', '(o˘◡˘o)', '(｡･ω･｡)', '(⁄ ⁄⟩⁄ ▽ ⁄⟨⁄ ⁄)', '(☆▽☆)', 'ʕっ•ᴥ•ʔっ', '(･ω･)ﾉ', '(ღ˘⌣˘ღ)', '(っ˘ڡ˘ς)', '（⋇＾3＾）⁄～☆', '（⌒▽⌒）', '(♡°▽°♡)', '(⊙︿⊙)', '(◡ ω ◡)', '(─‿─)', '(⌒‿⌒)', '(⋇°▽°⋇)', '(^▽^)', '♡＾▽＾♡', '(∩˃o˂∩)♡', '(✯◡✯❁)', '(￣3￣)', '(≡^∇^≡)', '(◠︿◠✿)', '(ᗒᗨᗕ)', '(♥ω♥⋇)', '(◜▿‾ ≡‾▿◝)', '（＾ω＾）', '(◠ω◕)', 'ʕ•́ᴥ•̀ʔっ', '(´• ω •`)ﾉ♡', 'o(〃＾▽＾〃)o', '(⋇ ⟩ω⟨)', '˚₊· ͟͟͞͞➳❥', '(ノ◕ヮ◕)ノ', '(ﾉ⋇⟩∀⟨)     )ﾉ♡', '(´•  ̫ •ू`)', '(◕ᴗ◕✿)', '( ´ ▽ ` )ﾉ', '(✿◕‿◕)', '✧･ﾟ： ⋇✧･ﾟ：⋇', '(´｡• ᵕ •｡`) ♡', '( ´ ▽ ` )', '(ﾉ◕ヮ◕)ﾉ⋇：･ﾟ✧', '(✯◡✯)', '＼(＾▽＾)／', '(⊙_☉)', '(•‿•)', '(˘⌣˘)♡(˘⌣˘)', '˚₊·͟͟͟͟͟͟͞͞͞͞͞͞➳❥', '(ɔˆ ³(ˆ⌣ˆc)', '(∩^o^)⊃━☆ﾟ.⋇･｡ﾟ', 'ლ(́◉◞౪◟◉‵ლ)', '✩°｡⋆⸜(⋇ ॑꒳ ॑⋇ )⸝', '(ʃƪ˘･ᴗ･˘)', '（⋇＾3＾)⁄～♡', '(              (•‾⌣‾•)و ̑̑♡', "。.：☆⋇：･'(⋇⌒―⌒⋇)))", '(˘⌣˘ )♡(˘⌣˘ )', '(✿◠‿◠)', '(^∇^)', '(¬‿¬ )', '☆.｡.：⋇･ﾟ☆.｡.：⋇･ﾟ', '(＾▽＾)', '✧⋇。٩(ˊᗜˋ⋇)و✧⋇。', '(^ε^)♪', '(｡•̀  ᴗ-)✧', '(☞ﾟ∀ﾟ)☞']


        # ランダムに選択された顔文字を表示
        memory_helper = random.choice(faces)
        self.memoname = input("覚えるときのメモを入力してください（空欄可）: ")

        self.memoname = self.memoname if self.memoname != "" else memory_helper

        print(self.memoname)
        input("メモはこれです。Enterで始めますよ。よろしいですね？")

        # 記録・デバッグ用のCSVファイル
        directory_name = os.path.join(self.script_directory, "data")
        file_name = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + f'_{self.memoname}_esp32_raw.csv'
        self.raw_csv_writer, file_obj_raw = self.create_csv_file(directory_name, file_name)

        self.raw_csv_writer.writerow(['Timestamp', 'log and response'])

        # データ用のCSVファイル
        file_name = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + f'_{self.memoname}_esp32_data.csv'
        self.data_csv_writer, file_obj_data = self.create_csv_file(directory_name, file_name)
        self.data_csv_writer.writerow(['Timestamp(python)','Timestamp(ESP32)','weight' ,'speed(delay)','speed(rpm)'])

        # 設定を表示・記録する
        self.show_and_save_settings()

        self.one_step_duration = (self.operation_during) / (self.planned_steps + 1)
        self.one_step_increase = (self.final_rpm - self.initial_rpm) / self.planned_steps if self.planned_steps != 0 else 0

        # マイコンとの通信を別スレッドで始める
        reveiver_thread = threading.Thread(target=self.receive_and_process)
        reveiver_thread.start()

        # グラフの更新をメインスレッドではじめる
        self.plot_graph()

        # 応答受信と処理を行う関数の終了を待機
        if reveiver_thread.is_alive():
            reveiver_thread.join()

        # プログラム終了時の共通処理
        self.send_command("stop_output\n")
        file_obj_raw.close()
        file_obj_data.close()
        self.ser.close()
        print("csv file saved. serial port closed.")
        
        # グラフの描画と保存
        file_name = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + f'_{self.memoname}_graph_image.png'
        save_path = os.path.join(directory_name, file_name)
        self.plot_graph_and_save(save_path, dpi=300)
        


def select_com_port():
    # 利用可能なCOMポートを取得
    ports = serial.tools.list_ports.comports()

    if not ports:
        print("利用可能なCOMポートが見つかりませんでした。")
        return None

    print("利用可能なCOMポート:")
    for i, port in enumerate(ports):
        print(f"{i+1}: {port.device} - {port.description}")

    # ユーザーにCOMポートを選択してもらう
    while True:
        try:
            choice = int(input("使用するCOMポートの番号を選択してください: "))
            if 1 <= choice <= len(ports):
                selected_port = ports[choice - 1].device
                return selected_port
            else:
                print("無効な選択です。もう一度試してください。")
        except ValueError:
            print("無効な入力です。整数を入力してください。")

if __name__ == "__main__":
    selected_port = select_com_port()

    if selected_port:
        print(f"選択されたCOMポート: {selected_port}")
        while True:
            collector = DataCollector(port=selected_port, baudrate=115200)
            collector.start()

    else:
        print("COMポートが選択されませんでした。")
