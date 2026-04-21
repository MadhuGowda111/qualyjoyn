import cv2
import mediapipe as mp
import numpy as np
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk

# -------------------------
# Global Variables
# -------------------------
video_path = ""
bg_choice = "studio"

# Background images
bg_map = {
    "studio": "backgrounds/studio.jpg",
    "indoor": "backgrounds/indoor.jpg",
    "street": "backgrounds/street.jpg"
}

# -------------------------
# Select Video
# -------------------------
def select_video():
    global video_path
    video_path = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.avi")])
    label_status.config(text=f"Selected: {os.path.basename(video_path)}")

# -------------------------
# Process Video
# -------------------------
def process_video():
    global video_path

    if not video_path:
        messagebox.showerror("Error", "Please select a video first")
        return

    output_path = "output.mp4"

    cap = cv2.VideoCapture(video_path)
    bg = cv2.imread(bg_map[bg_choice])

    mp_selfie = mp.solutions.selfie_segmentation
    segment = mp_selfie.SelfieSegmentation(model_selection=1)

    width = int(cap.get(3))
    height = int(cap.get(4))
    fps = cap.get(5)

    bg = cv2.resize(bg, (width, height))

    out = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))

    frame_count = 0

    label_status.config(text="Processing... ⏳")
    root.update()

    while True:
        ret, frame = cap.read()
        if not ret or frame_count > fps * 10:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = segment.process(rgb)

        mask = result.segmentation_mask > 0.5
        output = np.where(mask[..., None], frame, bg)

        out.write(output)
        frame_count += 1

    cap.release()
    out.release()

    label_status.config(text="Done ✅ Saved as output.mp4")
    messagebox.showinfo("Success", "Video processed successfully!")

# -------------------------
# Change Background
# -------------------------
def set_bg(choice):
    global bg_choice
    bg_choice = choice
    label_bg.config(text=f"Background: {choice}")

# -------------------------
# UI Design
# -------------------------
root = tk.Tk()
root.title("AI Background Remover")
root.geometry("400x400")

tk.Label(root, text="🎬 Video Background Remover", font=("Arial", 14)).pack(pady=10)

tk.Button(root, text="Upload Video", command=select_video).pack(pady=10)

label_status = tk.Label(root, text="No video selected")
label_status.pack()

tk.Label(root, text="Select Background").pack(pady=10)

tk.Button(root, text="Studio", command=lambda: set_bg("studio")).pack()
tk.Button(root, text="Indoor", command=lambda: set_bg("indoor")).pack()
tk.Button(root, text="Street", command=lambda: set_bg("street")).pack()

label_bg = tk.Label(root, text="Background: studio")
label_bg.pack(pady=10)

tk.Button(root, text="Process Video", command=process_video, bg="green", fg="white").pack(pady=20)

root.mainloop()