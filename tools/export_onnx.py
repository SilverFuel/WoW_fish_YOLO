"""Convert the original PyTorch checkpoint (best.pt) into the ONNX model the bot runs.

Only needed to rebuild models/splash.onnx. The bot itself does not need torch or ultralytics.

    pip install ultralytics onnx onnxslim onnxruntime
    python tools/export_onnx.py path/to/best.pt

best.pt is in the upstream repository (https://github.com/Hester60/WoW_fish_YOLO).
A .pt file is a pickle and runs code when loaded, so only convert checkpoints you trust.

The weights are stored as 16-bit floats and cast back to 32-bit when the model is loaded.
That halves the file, and costs nothing at run time because the cast happens once at load.
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIN_ELEMENTS_TO_COMPRESS = 1024


def store_weights_as_fp16(source, destination):
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    model = onnx.load(str(source))
    graph = model.graph
    initializers, casts = [], []

    for tensor in graph.initializer:
        values = numpy_helper.to_array(tensor)
        if tensor.data_type != TensorProto.FLOAT or values.size < MIN_ELEMENTS_TO_COMPRESS:
            initializers.append(tensor)
            continue

        half = values.astype(np.float16)
        if not np.isfinite(half).all():
            raise ValueError(f'{tensor.name} does not fit in 16-bit floats')

        stored_name = tensor.name + '_fp16'
        initializers.append(numpy_helper.from_array(half, stored_name))
        casts.append(helper.make_node('Cast', [stored_name], [tensor.name], to=TensorProto.FLOAT,
                                      name=tensor.name + '_to_fp32'))

    del graph.initializer[:]
    graph.initializer.extend(initializers)
    nodes = casts + list(graph.node)
    del graph.node[:]
    graph.node.extend(nodes)

    onnx.checker.check_model(model)
    onnx.save(model, str(destination))
    return len(casts)


def verify(checkpoint, onnx_path):
    """Compare the ONNX model with the PyTorch model on the same inputs."""
    import cv2
    import onnxruntime
    import torch
    from ultralytics import YOLO

    from fishbot import detector

    torch_model = YOLO(str(checkpoint)).model.float().eval()
    session = onnxruntime.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name

    screenshot = cv2.imread(str(ROOT / 'example.png'))
    random = np.random.default_rng(0)
    height, width = screenshot.shape[:2]
    frames = {'full window': screenshot,
              'center 75%': screenshot[height // 8:-height // 8, width // 8:-width // 8],
              'center 50%': screenshot[height // 4:-height // 4, width // 4:-width // 4],
              'noise': random.integers(0, 255, (720, 1280, 3), dtype=np.uint8)}

    worst_score, worst_box = 0.0, 0.0
    for name, frame in frames.items():
        for size in (640, 480, 320):
            tensor, _, _ = detector.letterbox(frame, size)
            with torch.no_grad():
                expected = torch_model(torch.from_numpy(tensor))
            expected = (expected[0] if isinstance(expected, (list, tuple)) else expected).numpy()
            actual = session.run(None, {input_name: tensor})[0]

            score_diff = float(np.abs(expected[0, 4] - actual[0, 4]).max())
            box_diff = float(np.abs(expected[0, :4] - actual[0, :4]).max())
            worst_score, worst_box = max(worst_score, score_diff), max(worst_box, box_diff)
            print(f'  {name:12} @{size}: input {tensor.shape[2]}x{tensor.shape[3]}, '
                  f'max score diff {score_diff:.2e}, max box diff {box_diff:.3f} px')

    print(f'Largest difference from the PyTorch model: score {worst_score:.2e}, box {worst_box:.3f} px')
    return worst_score, worst_box


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('checkpoint', type=Path, help='path to best.pt')
    parser.add_argument('--output', type=Path, default=ROOT / 'models' / 'splash.onnx')
    parser.add_argument('--skip-verify', action='store_true')
    args = parser.parse_args()

    from ultralytics import YOLO

    with tempfile.TemporaryDirectory() as work:
        # Export from a copy so the .onnx is not written next to the original checkpoint.
        checkpoint = Path(work) / 'model.pt'
        shutil.copy(args.checkpoint, checkpoint)
        exported = Path(YOLO(str(checkpoint)).export(format='onnx', dynamic=True, simplify=True, imgsz=640))

        args.output.parent.mkdir(parents=True, exist_ok=True)
        compressed = store_weights_as_fp16(exported, args.output)
        print(f'{exported.stat().st_size / 2**20:.1f} MiB as exported -> '
              f'{args.output.stat().st_size / 2**20:.1f} MiB ({compressed} tensors stored as fp16)')

        if not args.skip_verify:
            verify(checkpoint, args.output)

    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
