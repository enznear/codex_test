import gradio as gr
import os

port = int(os.environ.get("PORT", 7860))
root = os.environ.get("ROOT_PATH")


def greet(name: str) -> str:
    return f"Hello, {name}!"

iface = gr.Interface(fn=greet, inputs="text", outputs="text")

if __name__ == "__main__":
    iface.launch(server_name="0.0.0.0", server_port=port, root_path=root)
