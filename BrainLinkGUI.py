import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading, time, csv, collections
from cushy_serial import CushySerial
from BrainLinkParser import BrainLinkParser 


import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

PLOT_LEN = 200            
PLOT_UPDATE_MS = 250      
SERIAL_BAUD = 115200
TARGET_PORTS = ["COM4", "COM3"]  

eeg_data = {
    "attention": [], "meditation": [],
    "delta": [], "theta": [],
    "lowAlpha": [], "highAlpha": [],
    "lowBeta": [], "highBeta": [],
    "lowGamma": [], "highGamma": []
}

ratio_buffer = collections.deque(maxlen=PLOT_LEN)
att_buffer   = collections.deque(maxlen=PLOT_LEN)
time_buffer  = collections.deque(maxlen=PLOT_LEN)

serial_conn = None
parser = None
recording_thread = None
recording_stop_event = None
record_start_time = None
update_job = None


def safe_mean(lst):
    return sum(lst)/len(lst) if lst else 0.0

def compute_alpha_beta_ratio_from_means():
    la = safe_mean(eeg_data["lowAlpha"]); ha = safe_mean(eeg_data["highAlpha"])
    lb = safe_mean(eeg_data["lowBeta"]);  hb = safe_mean(eeg_data["highBeta"])
    denom = (lb + hb) if (lb + hb) != 0 else 1e-9
    return (la + ha) / denom

def compute_ratio_from_sample(sample):
    la = sample.get("lowAlpha",0) or 0
    ha = sample.get("highAlpha",0) or 0
    lb = sample.get("lowBeta",0) or 0
    hb = sample.get("highBeta",0) or 0
    denom = (lb + hb) if (lb + hb) != 0 else 1e-9
    return (la + ha) / denom

def onRaw(raw):
    return

def onEEG_cb(data):
    try:
        eeg_data["attention"].append(getattr(data, "attention", 0))
        eeg_data["meditation"].append(getattr(data, "meditation", 0))
        eeg_data["delta"].append(getattr(data, "delta", 0))
        eeg_data["theta"].append(getattr(data, "theta", 0))
        eeg_data["lowAlpha"].append(getattr(data, "lowAlpha", 0))
        eeg_data["highAlpha"].append(getattr(data, "highAlpha", 0))
        eeg_data["lowBeta"].append(getattr(data, "lowBeta", 0))
        eeg_data["highBeta"].append(getattr(data, "highBeta", 0))
        eeg_data["lowGamma"].append(getattr(data, "lowGamma", 0))
        eeg_data["highGamma"].append(getattr(data, "highGamma", 0))

    
        ratio = compute_ratio_from_sample({
            "lowAlpha": getattr(data, "lowAlpha",0),
            "highAlpha": getattr(data, "highAlpha",0),
            "lowBeta": getattr(data, "lowBeta",0),
            "highBeta": getattr(data, "highBeta",0)
        })
        ts = time.time() - (record_start_time or time.time())
        ratio_buffer.append(ratio)
        att_buffer.append(getattr(data, "attention", 0))
        time_buffer.append(ts)
    except Exception as e:
        print("onEEG exception:", e)

def onExtendEEG(data): return
def onGyro(x,y,z): return
def onRR(r1,r2,r3): return

def ensure_parser():
    global parser
    if parser is None:
        parser = BrainLinkParser(onEEG_cb, onExtendEEG, onGyro, onRR, onRaw)

def try_connect_fixed_ports():
    global serial_conn
    ensure_parser()
    try:
        if serial_conn:
            serial_conn.close()
    except Exception:
        pass
    serial_conn = None

    last_exc = None
    for p in TARGET_PORTS:
        try:
            serial_conn = CushySerial(p, SERIAL_BAUD)
            # attach handler
            @serial_conn.on_message()
            def _handler(msg: bytes):
                try:
                    parser.parse(msg)
                except Exception as e:
                    print("parser.parse error:", e)
            print(f"Connected to {p}")
            return p
        except Exception as e:
            last_exc = e
            print(f"Could not connect on {p} - {e}")
            # try next port
            serial_conn = None
            continue
    raise RuntimeError(f"Failed to open any target COM port. Last error: {last_exc}")

def disconnect_serial():
    global serial_conn
    try:
        if serial_conn:
            serial_conn.close()
    except Exception as e:
        print("Error closing serial:", e)
    finally:
        serial_conn = None

def recording_loop(stop_event):
    # this loop just keeps the record_start_time running; parser callbacks collect data
    global record_start_time
    record_start_time = time.time()
    while not stop_event.is_set():
        time.sleep(0.2)

class BrainLinkLiteApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BrainLink Lite v2.0 Recorder (COM4 -> COM3)")
        self.geometry("980x620")
        self.create_widgets()
        self.recording = False
        self.connected_port = None
        self.update_job = None

    def create_widgets(self):
        frm = ttk.Frame(self, padding=8); frm.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(frm); top.pack(fill=tk.X)
        self.btn_start = ttk.Button(top, text="Start", command=self.start_recording); self.btn_start.pack(side=tk.LEFT, padx=4)
        self.btn_stop  = ttk.Button(top, text="Stop",  command=self.stop_recording, state=tk.DISABLED); self.btn_stop.pack(side=tk.LEFT, padx=4)
        self.btn_save  = ttk.Button(top, text="Save CSV", command=self.save_csv, state=tk.DISABLED); self.btn_save.pack(side=tk.LEFT, padx=4)
        self.btn_quit  = ttk.Button(top, text="Quit", command=self.on_quit); self.btn_quit.pack(side=tk.RIGHT, padx=4)

        info = ttk.Frame(frm); info.pack(fill=tk.X, pady=6)
        ttk.Label(info, text="Device (expected): BrainLink Lite v2.0").pack(side=tk.LEFT)
        ttk.Label(info, text=" COM Port:").pack(side=tk.LEFT, padx=(12,2))
        self.lbl_port = ttk.Label(info, text="Not connected"); self.lbl_port.pack(side=tk.LEFT)
        ttk.Label(info, text="   Duration:").pack(side=tk.LEFT, padx=(12,2))
        self.lbl_duration = ttk.Label(info, text="0s"); self.lbl_duration.pack(side=tk.LEFT)

        # layout left/right: left numbers & text, right plot
        body = ttk.Frame(frm); body.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(body); left.pack(side=tk.LEFT, fill=tk.Y, padx=(0,8))
        right = ttk.Frame(body); right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # left live stats
        values_frame = ttk.LabelFrame(left, text="Live averages")
        values_frame.pack(fill=tk.X, pady=2)
        labels = ["attention","meditation","lowAlpha","highAlpha","lowBeta","highBeta","Alpha/Beta Ratio"]
        self.value_vars = {k: tk.StringVar(value="0.00") for k in labels}
        for i,k in enumerate(labels):
            ttk.Label(values_frame, text=k+":", width=12).grid(row=i, column=0, sticky=tk.W, padx=4, pady=2)
            ttk.Label(values_frame, textvariable=self.value_vars[k], width=10, relief=tk.SUNKEN).grid(row=i, column=1, sticky=tk.W, padx=4, pady=2)

        tb_frame = ttk.LabelFrame(left, text="Log")
        tb_frame.pack(fill=tk.BOTH, expand=True, pady=(8,0))
        self.text = scrolledtext.ScrolledText(tb_frame, width=40, height=20)
        self.text.pack(fill=tk.BOTH, expand=True)

        # right: matplotlib figure with two subplots (ratio & attention)
        fig = Figure(figsize=(6,4), dpi=100)
        self.ax = fig.add_subplot(211)
        self.ax.set_title("Alpha/Beta Ratio (live)")
        self.ax.set_ylabel("α/β")
        self.ax.grid(True)
        self.line_ratio, = self.ax.plot([], [], lw=1.6, label="α/β")
        self.ax.legend(loc="upper right")

        self.ax2 = fig.add_subplot(212, sharex=self.ax)
        self.ax2.set_title("Attention (live)")
        self.ax2.set_ylabel("attention")
        self.ax2.grid(True)
        self.line_att, = self.ax2.plot([], [], lw=1.2, label="attention", color="tab:orange")
        self.ax2.legend(loc="upper right")
        fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(fig, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def start_recording(self):
        global recording_thread, recording_stop_event, record_start_time
        if self.recording:
            return
        # clear old buffers
        for k in eeg_data: eeg_data[k].clear()
        ratio_buffer.clear(); att_buffer.clear(); time_buffer.clear()
        self.text.delete("1.0", tk.END)

        # try connect COM4 -> COM3
        try:
            port = try_connect_fixed_ports()
        except Exception as e:
            messagebox.showerror("Connection error", f"Could not connect to BrainLink Lite on COM4 or COM3:\n{e}")
            return

        self.connected_port = port
        self.lbl_port.config(text=str(port))
        self.text.insert(tk.END, f"Connected on {port}\n")

        # start recording thread
        recording_stop_event = threading.Event()
        recording_thread = threading.Thread(target=recording_loop, args=(recording_stop_event,), daemon=True)
        recording_thread.start()
        record_start_time = time.time()
        self.recording = True
        self.btn_start.config(state=tk.DISABLED); self.btn_stop.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.DISABLED)
        self._schedule_update()
        self._schedule_plot()

    def stop_recording(self):
        global recording_stop_event
        if not self.recording:
            return
        if self.update_job:
            self.after_cancel(self.update_job)
            self.update_job = None
        if recording_stop_event:
            recording_stop_event.set()
        time.sleep(0.1)
        self.recording = False
        self.btn_start.config(state=tk.NORMAL); self.btn_stop.config(state=tk.DISABLED)
        self.btn_save.config(state=tk.NORMAL)
        ratio = compute_alpha_beta_ratio_from_means()
        self.text.insert(tk.END, f"Final α/β Ratio: {ratio:.3f}\n")
        # disconnect serial (clean up)
        try:
            disconnect_serial()
            self.text.insert(tk.END, "Serial port closed.\n")
        except Exception as e:
            self.text.insert(tk.END, f"Error closing serial: {e}\n")

    def _schedule_update(self):
        self._update_display()
        self.update_job = self.after(1000, self._schedule_update)

    def _update_display(self):
        self.value_vars["attention"].set(f"{safe_mean(eeg_data['attention']):.2f}")
        self.value_vars["meditation"].set(f"{safe_mean(eeg_data['meditation']):.2f}")
        self.value_vars["lowAlpha"].set(f"{safe_mean(eeg_data['lowAlpha']):.2f}")
        self.value_vars["highAlpha"].set(f"{safe_mean(eeg_data['highAlpha']):.2f}")
        self.value_vars["lowBeta"].set(f"{safe_mean(eeg_data['lowBeta']):.2f}")
        self.value_vars["highBeta"].set(f"{safe_mean(eeg_data['highBeta']):.2f}")
        ratio = compute_alpha_beta_ratio_from_means()
        self.value_vars["Alpha/Beta Ratio"].set(f"{ratio:.3f}")

        if record_start_time:
            elapsed = int(time.time() - record_start_time)
            self.lbl_duration.config(text=f"{elapsed}s")
        # append a short log line
        self.text.insert(tk.END, f"Ratio: {ratio:.3f}\n")
        self.text.see(tk.END)

    def _schedule_plot(self):
        if self.recording:
            self._update_plot()
            self.after(PLOT_UPDATE_MS, self._schedule_plot)

    def _update_plot(self):
        xs = list(time_buffer)
        ys_r = list(ratio_buffer)
        ys_a = list(att_buffer)
        if not xs:
            return
        start = xs[0]
        xs = [x - start for x in xs]
        self.line_ratio.set_data(xs, ys_r)
        self.ax.relim(); self.ax.autoscale_view()
        self.line_att.set_data(xs, ys_a)
        self.ax2.relim(); self.ax2.autoscale_view()
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def save_csv(self):
        fname = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files","*.csv")])
        if not fname:
            return
        maxlen = max(len(v) for v in eeg_data.values())
        header = [
            "index","attention","meditation","delta","theta","lowAlpha","highAlpha","lowBeta","highBeta","lowGamma","highGamma",
            "Alpha/Beta_Ratio", "Theta/Beta_Ratio"  # Do not prefer Theta/Beta_Ratio, I will have to remove it later.
        ]
        band_keys = [
            "attention","meditation","delta","theta","lowAlpha","highAlpha",
            "lowBeta","highBeta","lowGamma","highGamma"
        ]
        
        with open(fname, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            def safe_divide(numerator, denominator):
                return numerator / denominator if denominator != 0 else 0.0

            for i in range(maxlen):
                row = [i]
                sample_data = {} 
                for k in band_keys:
                    val = eeg_data[k][i] if i < len(eeg_data[k]) else ""
                    row.append(val)
                    if isinstance(val, (int, float)):
                        sample_data[k] = val
                alpha_power = sample_data.get("lowAlpha", 0) + sample_data.get("highAlpha", 0)
                theta_power = sample_data.get("theta", 0)
                beta_power = sample_data.get("lowBeta", 0) + sample_data.get("highBeta", 0)
                alpha_beta_ratio = safe_divide(alpha_power, beta_power)
                theta_beta_ratio = safe_divide(theta_power, beta_power)
                row.append(f"{alpha_beta_ratio:.3f}")
                row.append(f"{theta_beta_ratio:.3f}")
                writer.writerow(row)    
        messagebox.showinfo("Saved", f"Saved session to {fname}")

    def on_quit(self):
        if self.recording:
            if not messagebox.askyesno("Quit", "Recording in progress. Stop and quit?"):
                return
            self.stop_recording()
        try:
            disconnect_serial()
        except:
            pass
        self.destroy()

if __name__ == "__main__":
    app = BrainLinkLiteApp()
    app.mainloop()
