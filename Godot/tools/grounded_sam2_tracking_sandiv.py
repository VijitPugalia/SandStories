# Adapted from IDEA-Research/Grounded-SAM-2 at commit
# b7a9c29f196edff0eb54dbe14588d7ae5e3dde28. Licensed under the Apache
# License, Version 2.0. SandStories adds capture-specific detection filtering,
# continuous-ID tracking, reverse tracking, and ProPainter mask export.

import argparse
import os
import cv2
import torch
import numpy as np
import supervision as sv
from PIL import Image
from sam2.build_sam import build_sam2_video_predictor, build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
from utils.track_utils import sample_points_from_masks
from utils.video_utils import create_video_from_images
from utils.common_utils import CommonUtils
from utils.mask_dictionary_model import MaskDictionaryModel, ObjectInfo
import json
import copy
from pathlib import Path

# This demo shows the continuous object tracking plus reverse tracking with Grounding DINO and SAM 2
"""
Step 1: Environment settings and model initialization
"""
parser = argparse.ArgumentParser(
    description=(
        "Run the upstream Grounded-SAM-2 continuous-ID plus reverse-tracking "
        "pipeline and export binary ProPainter masks."
    )
)
parser.add_argument("--video-dir", type=Path, required=True)
parser.add_argument("--output-dir", type=Path, required=True)
parser.add_argument("--text", default="hand. arm.")
parser.add_argument("--step", type=int, default=20)
parser.add_argument("--box-threshold", type=float, default=0.25)
parser.add_argument("--text-threshold", type=float, default=0.25)
parser.add_argument(
    "--sam2-checkpoint",
    type=Path,
    default=Path("./checkpoints/sam2.1_hiera_large.pt"),
)
parser.add_argument(
    "--sam2-config",
    default="configs/sam2.1/sam2.1_hiera_l.yaml",
)
parser.add_argument(
    "--grounding-model",
    default="IDEA-Research/grounding-dino-tiny",
)
parser.add_argument("--draw-results", action="store_true")
parser.add_argument("--max-box-area-ratio", type=float, default=0.5,
                    help="Drop detections whose box covers more than this fraction of the frame "
                         "(guards against near-full-frame phantom boxes; 1.0 disables)")
args = parser.parse_args()

if not args.text.islower() or not args.text.endswith("."):
    raise ValueError("--text must be lowercase and end with a period")
if args.step <= 0:
    raise ValueError("--step must be positive")

if torch.cuda.is_available():
    compute_capability = torch.cuda.get_device_properties(0).major
    autocast_dtype = (
        torch.bfloat16 if compute_capability >= 8 else torch.float16
    )
    torch.autocast(
        device_type="cuda",
        dtype=autocast_dtype,
    ).__enter__()

if torch.cuda.get_device_properties(0).major >= 8:
    # turn on tfloat32 for Ampere GPUs (https://pytorch.org/docs/stable/notes/cuda.html#tensorfloat-32-tf32-on-ampere-devices)
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

# init sam image predictor and video predictor model
sam2_checkpoint = str(args.sam2_checkpoint)
model_cfg = args.sam2_config
device = "cuda" if torch.cuda.is_available() else "cpu"
print("device", device)

video_predictor = build_sam2_video_predictor(model_cfg, sam2_checkpoint)
sam2_image_model = build_sam2(model_cfg, sam2_checkpoint, device=device)
image_predictor = SAM2ImagePredictor(sam2_image_model)


# init grounding dino model from huggingface
model_id = args.grounding_model
processor = AutoProcessor.from_pretrained(model_id)
grounding_model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(device)


# setup the input image and text prompt for SAM 2 and Grounding DINO
# VERY important: text queries need to be lowercased + end with a dot
text = args.text

# `video_dir` a directory of JPEG frames with filenames like `<frame_index>.jpg`
source_video_dir = args.video_dir.resolve()
source_pngs = sorted(source_video_dir.glob("*.png"))
source_jpegs = sorted(source_video_dir.glob("*.jpg"))
if source_pngs and not source_jpegs:
    staged_video_dir = args.output_dir.resolve() / "input_jpegs"
    staged_video_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_pngs:
        destination = staged_video_dir / f"{source_path.stem}.jpg"
        if destination.exists():
            continue
        Image.open(source_path).convert("RGB").save(
            destination,
            quality=100,
            subsampling=0,
        )
    video_dir = str(staged_video_dir)
else:
    video_dir = str(source_video_dir)
# 'output_dir' is the directory to save the annotated frames
output_dir = str(args.output_dir.resolve())
# 'output_video_path' is the path to save the final video
output_video_path = os.path.join(output_dir, "tracking.mp4")
# create the output directory
mask_data_dir = os.path.join(output_dir, "mask_data")
json_data_dir = os.path.join(output_dir, "json_data")
result_dir = os.path.join(output_dir, "result")
CommonUtils.creat_dirs(mask_data_dir)
CommonUtils.creat_dirs(json_data_dir)
# scan all the JPEG frame names in this directory
frame_names = [
    p for p in os.listdir(video_dir)
    if os.path.splitext(p)[-1] in [".jpg", ".jpeg", ".JPG", ".JPEG", ".png", ".PNG"]
]
frame_names.sort(key=lambda p: int(os.path.splitext(p)[0]))

# init video predictor state
inference_state = video_predictor.init_state(video_path=video_dir)
step = args.step

sam2_masks = MaskDictionaryModel()
sam2_masks.mask_height = inference_state["video_height"]
sam2_masks.mask_width = inference_state["video_width"]
PROMPT_TYPE_FOR_VIDEO = "mask" # box, mask or point
objects_count = 0
frame_object_count = {}
"""
Step 2: Prompt Grounding DINO and SAM image predictor to get the box and mask for all frames
"""
print("Total frames:", len(frame_names))
for start_frame_idx in range(0, len(frame_names), step):
# prompt grounding dino to get the box coordinates on specific frame
    print("start_frame_idx", start_frame_idx)
    # continue
    img_path = os.path.join(video_dir, frame_names[start_frame_idx])
    image = Image.open(img_path).convert("RGB")
    image_base_name = frame_names[start_frame_idx].split(".")[0]
    mask_dict = MaskDictionaryModel(promote_type = PROMPT_TYPE_FOR_VIDEO, mask_name = f"mask_{image_base_name}.npy")

    # run Grounding DINO on the image
    inputs = processor(images=image, text=text, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = grounding_model(**inputs)

    results = processor.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        box_threshold=args.box_threshold,
        text_threshold=args.text_threshold,
        target_sizes=[image.size[::-1]]
    )

    # prompt SAM image predictor to get the mask for the object
    image_predictor.set_image(np.array(image.convert("RGB")))

    # process the detection results
    input_boxes = results[0]["boxes"] # .cpu().numpy()
    # print("results[0]",results[0])
    OBJECTS = results[0]["labels"]
    # filter near-full-frame phantom boxes (grounding-dino artifact on empty scenes)
    if args.max_box_area_ratio < 1.0:
        img_w, img_h = image.size
        keep = [
            i for i in range(input_boxes.shape[0])
            if (input_boxes[i][2] - input_boxes[i][0]) * (input_boxes[i][3] - input_boxes[i][1])
            <= args.max_box_area_ratio * img_w * img_h
        ]
        if len(keep) < input_boxes.shape[0]:
            input_boxes = input_boxes[keep]
            OBJECTS = [OBJECTS[i] for i in keep]
    if input_boxes.shape[0] != 0:

        # prompt SAM 2 image predictor to get the mask for the object
        masks, scores, logits = image_predictor.predict(
            point_coords=None,
            point_labels=None,
            box=input_boxes,
            multimask_output=False,
        )
        # convert the mask shape to (n, H, W)
        if masks.ndim == 2:
            masks = masks[None]
            scores = scores[None]
            logits = logits[None]
        elif masks.ndim == 4:
            masks = masks.squeeze(1)
        """
        Step 3: Register each object's positive points to video predictor
        """

        # If you are using point prompts, we uniformly sample positive points based on the mask
        if mask_dict.promote_type == "mask":
            mask_dict.add_new_frame_annotation(mask_list=torch.tensor(masks).to(device), box_list=torch.tensor(input_boxes), label_list=OBJECTS)
        else:
            raise NotImplementedError("SAM 2 video predictor only support mask prompts")
    else:
        print("No object detected in the frame, skip merge the frame merge {}".format(frame_names[start_frame_idx]))
        mask_dict = sam2_masks

    """
    Step 4: Propagate the video predictor to get the segmentation results for each frame
    """
    objects_count = mask_dict.update_masks(tracking_annotation_dict=sam2_masks, iou_threshold=0.8, objects_count=objects_count)
    frame_object_count[start_frame_idx] = objects_count
    print("objects_count", objects_count)

    if len(mask_dict.labels) == 0:
        mask_dict.save_empty_mask_and_json(mask_data_dir, json_data_dir, image_name_list = frame_names[start_frame_idx:start_frame_idx+step])
        print("No object detected in the frame, skip the frame {}".format(start_frame_idx))
        continue
    else:
        video_predictor.reset_state(inference_state)

        for object_id, object_info in mask_dict.labels.items():
            frame_idx, out_obj_ids, out_mask_logits = video_predictor.add_new_mask(
                    inference_state,
                    start_frame_idx,
                    object_id,
                    object_info.mask,
                )

        video_segments = {}  # output the following {step} frames tracking masks
        for out_frame_idx, out_obj_ids, out_mask_logits in video_predictor.propagate_in_video(inference_state, max_frame_num_to_track=step, start_frame_idx=start_frame_idx):
            frame_masks = MaskDictionaryModel()

            for i, out_obj_id in enumerate(out_obj_ids):
                out_mask = (out_mask_logits[i] > 0.0) # .cpu().numpy()
                object_info = ObjectInfo(instance_id = out_obj_id, mask = out_mask[0], class_name = mask_dict.get_target_class_name(out_obj_id), logit=mask_dict.get_target_logit(out_obj_id))
                object_info.update_box()
                frame_masks.labels[out_obj_id] = object_info
                image_base_name = frame_names[out_frame_idx].split(".")[0]
                frame_masks.mask_name = f"mask_{image_base_name}.npy"
                frame_masks.mask_height = out_mask.shape[-2]
                frame_masks.mask_width = out_mask.shape[-1]

            video_segments[out_frame_idx] = frame_masks
            sam2_masks = copy.deepcopy(frame_masks)

        print("video_segments:", len(video_segments))
    """
    Step 5: save the tracking masks and json files
    """
    for frame_idx, frame_masks_info in video_segments.items():
        mask = frame_masks_info.labels
        mask_img = torch.zeros(frame_masks_info.mask_height, frame_masks_info.mask_width)
        for obj_id, obj_info in mask.items():
            mask_img[obj_info.mask == True] = obj_id

        mask_img = mask_img.numpy().astype(np.uint16)
        np.save(os.path.join(mask_data_dir, frame_masks_info.mask_name), mask_img)

        json_data_path = os.path.join(json_data_dir, frame_masks_info.mask_name.replace(".npy", ".json"))
        frame_masks_info.to_json(json_data_path)


if args.draw_results:
    CommonUtils.draw_masks_and_box_with_supervision(
        video_dir,
        mask_data_dir,
        json_data_dir,
        result_dir,
    )

print("try reverse tracking")
start_object_id = 0
object_info_dict = {}
for frame_idx, current_object_count in frame_object_count.items():
    print("reverse tracking frame", frame_idx, frame_names[frame_idx])
    previous_object_count = start_object_id
    if frame_idx != 0:
        video_predictor.reset_state(inference_state)
        image_base_name = frame_names[frame_idx].split(".")[0]
        json_data_path = os.path.join(json_data_dir, f"mask_{image_base_name}.json")
        json_data = MaskDictionaryModel().from_json(json_data_path)
        mask_data_path = os.path.join(mask_data_dir, f"mask_{image_base_name}.npy")
        mask_array = np.load(mask_data_path)
        for object_id in range(start_object_id+1, current_object_count+1):
            print("reverse tracking object", object_id)
            object_info_dict[object_id] = json_data.labels[object_id]
            video_predictor.add_new_mask(inference_state, frame_idx, object_id, mask_array == object_id)
    start_object_id = current_object_count
    if current_object_count == 0:
        continue
    if frame_idx != 0 and current_object_count <= previous_object_count:
        continue


    for out_frame_idx, out_obj_ids, out_mask_logits in video_predictor.propagate_in_video(inference_state, max_frame_num_to_track=step*2,  start_frame_idx=frame_idx, reverse=True):
        image_base_name = frame_names[out_frame_idx].split(".")[0]
        json_data_path = os.path.join(json_data_dir, f"mask_{image_base_name}.json")
        json_data = MaskDictionaryModel().from_json(json_data_path)
        mask_data_path = os.path.join(mask_data_dir, f"mask_{image_base_name}.npy")
        mask_array = np.load(mask_data_path)
        # merge the reverse tracking masks with the original masks
        for i, out_obj_id in enumerate(out_obj_ids):
            out_mask = (out_mask_logits[i] > 0.0).cpu()
            if out_mask.sum() == 0:
                print("no mask for object", out_obj_id, "at frame", out_frame_idx)
                continue
            object_info = object_info_dict[out_obj_id]
            object_info.mask = out_mask[0]
            object_info.update_box()
            json_data.labels[out_obj_id] = object_info
            mask_array = np.where(mask_array != out_obj_id, mask_array, 0)
            mask_array[object_info.mask] = out_obj_id

        np.save(mask_data_path, mask_array)
        json_data.to_json(json_data_path)





"""
Step 6: Draw the results and save the video
"""
if args.draw_results:
    CommonUtils.draw_masks_and_box_with_supervision(
        video_dir,
        mask_data_dir,
        json_data_dir,
        result_dir + "_reverse",
    )
    create_video_from_images(
        result_dir + "_reverse",
        output_video_path,
        frame_rate=15,
    )

binary_mask_dir = Path(output_dir) / "binary_masks"
binary_mask_dir.mkdir(parents=True, exist_ok=True)
active_frames = 0
areas = []
for frame_name in frame_names:
    stem = Path(frame_name).stem
    mask_path = Path(mask_data_dir) / f"mask_{stem}.npy"
    if not mask_path.exists():
        raise FileNotFoundError(mask_path)
    instance_mask = np.load(mask_path)
    binary_mask = instance_mask > 0
    area = int(np.count_nonzero(binary_mask))
    active_frames += int(area > 0)
    areas.append(area)
    destination = binary_mask_dir / f"{stem}.png"
    if not cv2.imwrite(
        str(destination),
        binary_mask.astype(np.uint8) * 255,
    ):
        raise OSError(f"Failed to write {destination}")

report = {
    "name": "grounded_sam2_continuous_id_plus_reverse",
    "upstreamCommit": "b7a9c29f196edff0eb54dbe14588d7ae5e3dde28",
    "videoDir": video_dir,
    "sourceVideoDir": str(source_video_dir),
    "frameCount": len(frame_names),
    "activeFrameCount": active_frames,
    "textPrompt": text,
    "groundingModel": model_id,
    "sam2Checkpoint": sam2_checkpoint,
    "sam2Config": model_cfg,
    "step": step,
    "boxThreshold": args.box_threshold,
    "textThreshold": args.text_threshold,
    "maxBoxAreaRatio": args.max_box_area_ratio,
    "maskPostprocessing": "none",
    "surfaceClipping": False,
    "areaPixels": {
        "minimum": min(areas),
        "median": float(np.median(areas)),
        "maximum": max(areas),
    },
}
(Path(output_dir) / "mask_report.json").write_text(
    json.dumps(report, indent=2),
    encoding="utf-8",
)
print(json.dumps(report, indent=2), flush=True)
