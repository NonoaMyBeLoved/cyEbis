from __future__ import annotations

import os
import shutil
import subprocess
import sys


PACKAGES = ["torch", "torchvision", "torchaudio"]
CUDA_WHEELS = ["cu128", "cu126", "cu124", "cu121", "cu118"]


def run(command: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    print(f"\n> {' '.join(command)}", flush=True)
    return subprocess.run(command, text=True, check=check)


def nvidia_summary() -> None:
    if not shutil.which("nvidia-smi"):
        print("nvidia-smi를 찾지 못했습니다. NVIDIA 드라이버가 설치되어 있는지 확인하세요.")
        return

    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        print("감지된 NVIDIA GPU:")
        for line in result.stdout.strip().splitlines():
            print(f"  {line.strip()}")
    else:
        print("nvidia-smi 실행은 됐지만 GPU 정보를 읽지 못했습니다.")


def torch_cuda_ok() -> bool:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import torch; "
                "print('torch=' + torch.__version__); "
                "print('torch CUDA=' + str(torch.version.cuda)); "
                "print('cuda_available=' + str(torch.cuda.is_available())); "
                "print('device=' + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'))"
            ),
        ],
        text=True,
    )
    return result.returncode == 0


def cuda_available() -> bool:
    result = subprocess.run(
        [sys.executable, "-c", "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"],
        text=True,
    )
    return result.returncode == 0


def install_cuda_wheel(tag: str) -> bool:
    index_url = f"https://download.pytorch.org/whl/{tag}"
    result = run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
            *PACKAGES,
            "--index-url",
            index_url,
        ]
    )
    if result.returncode != 0:
        print(f"{tag} wheel 설치에 실패했습니다. 다음 후보를 시도합니다.")
        return False

    print(f"{tag} wheel 설치 후 CUDA 인식 상태를 확인합니다.")
    torch_cuda_ok()
    return cuda_available()


def requested_candidates() -> list[str]:
    requested = os.environ.get("CYEBIS_TORCH_CUDA", "").strip().lower()
    if not requested:
        return CUDA_WHEELS
    if requested not in CUDA_WHEELS:
        print(f"알 수 없는 CYEBIS_TORCH_CUDA 값입니다: {requested}")
        print(f"사용 가능한 값: {', '.join(CUDA_WHEELS)}")
        sys.exit(2)
    return [requested]


def main() -> int:
    print("cyEbis GPU PyTorch 설치 도우미")
    print("현재 Python:", sys.executable)
    nvidia_summary()

    print("\n현재 PyTorch 상태:")
    torch_cuda_ok()
    if cuda_available():
        print("\n이미 CUDA PyTorch를 사용할 수 있습니다.")
        return 0

    print("\nCUDA 지원 PyTorch wheel을 자동으로 시도합니다.")
    for tag in requested_candidates():
        print(f"\n=== PyTorch CUDA 후보: {tag} ===")
        if install_cuda_wheel(tag):
            print(f"\n성공: PyTorch가 GPU를 인식했습니다. ({tag})")
            return 0

    print("\n자동 설치 후보가 모두 실패했습니다.")
    print("NVIDIA 드라이버를 최신 버전으로 업데이트한 뒤 다시 실행하거나, PyTorch 공식 설치 페이지의 명령어를 사용하세요.")
    print("https://pytorch.org/get-started/locally/")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
