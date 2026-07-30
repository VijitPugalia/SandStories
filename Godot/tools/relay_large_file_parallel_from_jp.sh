#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 SOURCE_ON_JP DESTINATION EXPECTED_BYTES [PARALLEL_PARTS]" >&2
  exit 2
fi

SOURCE_ON_JP=$1
DESTINATION=$2
EXPECTED_BYTES=$3
PARALLEL_PARTS=${4:-8}
JP_HOST=${JP_HOST:?Set JP_HOST to the SSH relay host}
JP_KEY=${JP_KEY:-}
PART_DIR="${DESTINATION}.relay_parts"
SSH_ARGS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${JP_KEY}" ]]; then
  SSH_ARGS+=(-i "${JP_KEY}")
fi

mkdir -p "${PART_DIR}" "$(dirname "${DESTINATION}")"

declare -a PIDS=()
for ((part = 0; part < PARALLEL_PARTS; part++)); do
  offset=$((EXPECTED_BYTES * part / PARALLEL_PARTS))
  end=$((EXPECTED_BYTES * (part + 1) / PARALLEL_PARTS))
  length=$((end - offset))
  part_path="${PART_DIR}/part_$(printf '%03d' "${part}")"
  partial_path="${part_path}.partial"

  if [[ -f "${part_path}" ]] &&
     [[ "$(stat -c '%s' "${part_path}")" -eq "${length}" ]]; then
    continue
  fi

  (
    partial_bytes=0
    if [[ -f "${partial_path}" ]]; then
      partial_bytes=$(stat -c '%s' "${partial_path}")
      if [[ "${partial_bytes}" -gt "${length}" ]]; then
        rm -f "${partial_path}"
        partial_bytes=0
      elif [[ "${partial_bytes}" -eq "${length}" ]]; then
        mv "${partial_path}" "${part_path}"
        exit 0
      fi
    fi
    source_offset=$((offset + partial_bytes))
    remaining=$((length - partial_bytes))
    ssh "${SSH_ARGS[@]}" \
      "${JP_HOST}" \
      "dd if='${SOURCE_ON_JP}' iflag=skip_bytes,count_bytes skip=${source_offset} count=${remaining} bs=8M status=none" \
      >> "${partial_path}"
    actual_bytes=$(stat -c '%s' "${partial_path}")
    if [[ "${actual_bytes}" -ne "${length}" ]]; then
      echo "part ${part}: expected ${length} bytes, got ${actual_bytes}" >&2
      exit 1
    fi
    mv "${partial_path}" "${part_path}"
  ) &
  PIDS+=("$!")
done

for pid in "${PIDS[@]}"; do
  wait "${pid}"
done

truncate -s "${EXPECTED_BYTES}" "${DESTINATION}"
for ((part = 0; part < PARALLEL_PARTS; part++)); do
  offset=$((EXPECTED_BYTES * part / PARALLEL_PARTS))
  end=$((EXPECTED_BYTES * (part + 1) / PARALLEL_PARTS))
  length=$((end - offset))
  part_path="${PART_DIR}/part_$(printf '%03d' "${part}")"
  actual_bytes=$(stat -c '%s' "${part_path}")
  if [[ "${actual_bytes}" -ne "${length}" ]]; then
    echo "part ${part}: expected ${length} bytes, got ${actual_bytes}" >&2
    exit 1
  fi
  dd if="${part_path}" of="${DESTINATION}" oflag=seek_bytes \
    seek="${offset}" bs=8M conv=notrunc status=none
done

actual_total=$(stat -c '%s' "${DESTINATION}")
if [[ "${actual_total}" -ne "${EXPECTED_BYTES}" ]]; then
  echo "destination: expected ${EXPECTED_BYTES} bytes, got ${actual_total}" >&2
  exit 1
fi

sha256sum "${DESTINATION}"
