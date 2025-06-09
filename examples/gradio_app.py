import gradio as gr
import os

port = int(os.environ.get("PORT", 7860))


def greet(name: str) -> str:
    return f"Hello, {name}!"

iface = gr.Interface(fn=greet, inputs="text", outputs="text")

if __name__ == "__main__":
    iface.launch(server_name="0.0.0.0", server_port=port)
