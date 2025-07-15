import gradio as gr
from fastapi import FastAPI
from fastapi.responses import FileResponse
import os

# Path to a sample video file (provide your own file in practice)
VIDEO_PATH = os.environ.get("VIDEO_PATH", "sample.mp4")

app = FastAPI()

@app.get("/download")
def download():
    if not os.path.exists(VIDEO_PATH):
        return {"error": "video not found"}
    return FileResponse(VIDEO_PATH, media_type="video/mp4", filename=os.path.basename(VIDEO_PATH))


def generate_video(text):
    # Dummy implementation just returns existing video file
    return VIDEO_PATH

with gr.Blocks() as demo:
    name = gr.Textbox(label="Your name")
    video = gr.Video()
    btn = gr.Button("Create Video")
    btn.click(generate_video, name, video)
    gr.HTML('<a href="/download" download class="gr-button">Download</a>')

if __name__ == "__main__":
    demo.launch(server_port=int(os.environ.get("PORT", 7860)), server_name="0.0.0.0", fastapi_app=app)
