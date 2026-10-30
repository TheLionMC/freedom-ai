import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(
        description="Convert the trained Hugging Face model to GGUF with llama.cpp."
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "out" / "ddr" / "merged",
        help="merged Hugging Face model directory",
    )
    parser.add_argument(
        "--llama-cpp",
        type=Path,
        default=ROOT / "llama.cpp",
        help="llama.cpp checkout directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "out" / "ddr" / "ddr-f16.gguf",
        help="output GGUF file",
    )
    parser.add_argument(
        "--outtype",
        choices=["f32", "f16", "bf16", "q8_0", "tq1_0", "tq2_0", "auto"],
        default="f16",
        help="GGUF output type (default: f16)",
    )
    args = parser.parse_args()

    model = args.model.resolve()
    converter = args.llama_cpp.resolve() / "convert_hf_to_gguf.py"
    output = args.output.resolve()

    if not model.is_dir():
        raise SystemExit(f"Model directory not found: {model}")
    if not (model / "config.json").is_file():
        raise SystemExit(f"Model config not found in: {model}")
    if not converter.is_file():
        raise SystemExit(
            f"llama.cpp converter not found: {converter}\n"
            "Clone llama.cpp or pass its directory with --llama-cpp."
        )
    if importlib.util.find_spec("sentencepiece") is None:
        raise SystemExit(
            "The active Python environment is missing sentencepiece.\n"
            f'Install it with: "{sys.executable}" -m pip install sentencepiece'
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(converter),
        str(model),
        "--outfile",
        str(output),
        "--outtype",
        args.outtype,
    ]
    print(f"Converting {model} to {output} ({args.outtype})...")
    subprocess.run(command, cwd=converter.parent, check=True)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"Conversion finished without creating a valid output: {output}")
    print(f"Created {output} ({output.stat().st_size / (1024 ** 3):.2f} GiB)")


if __name__ == "__main__":
    main()
