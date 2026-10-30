import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from shared import MODERATOR, render


ROOT = Path(__file__).resolve().parent
END = "<|im_end|>"
OPPONENT = "solidarity_us"
SCENARIO = "In einer Diskussion über Gesellschaft und Alltag."


def find_model():
    candidates = [
        ROOT / "out" / "ddr" / "ddr-Q4_K_M.gguf",
        ROOT / "out" / "ddr" / "ddr-f16.gguf",
    ]
    return next((path for path in candidates if path.is_file()), None)


def find_server():
    candidates = [
        ROOT / "llama.cpp" / "build" / "bin" / "Release" / "llama-server.exe",
        ROOT / "llama.cpp" / "build" / "bin" / "llama-server.exe",
        ROOT / "llama.cpp" / "build" / "bin" / "Release" / "llama-server",
        ROOT / "llama.cpp" / "build" / "bin" / "llama-server",
        ROOT / "llama.cpp" / "llama-server.exe",
        ROOT / "llama.cpp" / "llama-server",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return shutil.which("llama-server") or shutil.which("llama-server.exe")


def wait_for_server(process, base_url, timeout, log_file):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_file.flush()
            log_file.seek(0)
            details = log_file.read().strip()
            raise RuntimeError(
                f"llama-server exited with code {process.returncode}."
                + (f"\nServer output:\n{details[-4000:]}" if details else "")
            )
        try:
            with urlopen(f"{base_url}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(1)

    raise RuntimeError(
        f"llama-server did not become ready within {timeout} seconds. "
        "Check that the model fits in memory and try a smaller --context."
    )


def generate(base_url, prompt, args):
    body = json.dumps({
        "prompt": prompt,
        "n_predict": args.tokens,
        "temperature": args.temperature,
        "stop": [END],
        "cache_prompt": True,
    }).encode("utf-8")
    request = Request(
        f"{base_url}/completion",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=None) as response:
            result = json.load(response)
    except URLError as error:
        raise RuntimeError(f"Could not request a completion from llama-server: {error}") from error

    content = result.get("content")
    if not isinstance(content, str):
        raise RuntimeError("llama-server returned a response without completion text.")
    return content.strip()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Chat with the locally trained DDR model using llama.cpp."
    )
    parser.add_argument("--model", type=Path, help="GGUF model (default: out/ddr/*.gguf)")
    parser.add_argument("--server", type=Path, help="path to llama-server executable")
    parser.add_argument("--host", default="127.0.0.1", help="server bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="server port (default: 8080)")
    parser.add_argument("--context", type=int, default=4096, help="context size (default: 4096)")
    parser.add_argument("--tokens", type=int, default=128, help="maximum generated tokens per turn")
    parser.add_argument("--gpu-layers", type=int, default=99, help="GPU layers to offload (default: 99)")
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--startup-timeout", type=int, default=300)
    return parser.parse_args()


def main():
    args = parse_args()
    model = args.model or find_model()
    if model is None or not model.is_file():
        raise SystemExit(
            "No GGUF model found. Expected out\\ddr\\ddr-f16.gguf or "
            "out\\ddr\\ddr-Q4_K_M.gguf; pass --model to choose another file."
        )
    model = model.resolve()

    server = args.server or find_server()
    if server is None or not Path(server).is_file():
        raise SystemExit(
            "Could not find llama-server. Build llama.cpp or download a Windows "
            "release, then pass its executable with --server."
        )
    server = str(Path(server).resolve())

    if args.port < 1 or args.port > 65535:
        raise SystemExit("--port must be between 1 and 65535.")
    if args.context < 1 or args.tokens < 1 or args.startup_timeout < 1:
        raise SystemExit("--context, --tokens, and --startup-timeout must be positive.")
    if args.gpu_layers < 0:
        raise SystemExit("--gpu-layers cannot be negative.")

    base_url = f"http://{args.host}:{args.port}"
    command = [
        server,
        "--model", str(model),
        "--host", args.host,
        "--port", str(args.port),
        "--ctx-size", str(args.context),
        "--n-gpu-layers", str(args.gpu_layers),
    ]
    print(f"Loading {model.name}; this may take a little while...")

    with open("llama-server.log", "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for_server(process, base_url, args.startup_timeout, log_file)
            print("Ready. Type :reset to clear the conversation or :quit to exit.")
            history = [(MODERATOR, SCENARIO)]
            while True:
                try:
                    message = input("\nYou: ").strip()
                except EOFError:
                    break
                if not message:
                    continue
                if message.lower() in {":quit", ":exit"}:
                    break
                if message.lower() == ":reset":
                    history = [(MODERATOR, SCENARIO)]
                    print("Conversation cleared.")
                    continue

                prompt = render(
                    history,
                    partial=(OPPONENT, message),
                    next_speaker="ddr",
                )
                answer = generate(base_url, prompt, args)
                if not answer:
                    print(
                        "DDR generated no text. Try a specific statement or question; "
                        "the model may have stopped immediately."
                    )
                    continue
                if answer.startswith("<|interrupt|>"):
                    answer = answer.removeprefix("<|interrupt|>").strip()
                    print(f"DDR (interrupt): {answer}")
                else:
                    print(f"DDR: {answer}")
                history.extend([(OPPONENT, message), ("ddr", answer)])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
