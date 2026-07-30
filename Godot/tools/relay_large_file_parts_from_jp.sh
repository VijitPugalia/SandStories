#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 5 ]]; then
  echo "usage: $0 SOURCE_ON_JP DESTINATION EXPECTED_BYTES PARALLEL_PARTS PART_INDEX..." >&2
  exit 2
fi

SOURCE_ON_JP=$1
DESTINATION=$2
EXPECTED_BYTES=$3
PARALLEL_PARTS=$4
shift 4
PART_INDICES=("$@")
JP_HOST=${JP_HOST:?Set JP_HOST to the SSH relay host}
JP_KEY=${JP_KEY:-}
PART_DIR="${DESTINATION}.relay_parts"
SSH_ARGS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${JP_KEY}" ]]; then
  SSH_ARGS+=(-i "${JP_KEY}")
fi

resume_part() {
  local part=$1
  local offset
  local end
  local length
  local part_path
  local partial_path
  local partial_bytes=0
  local source_offset
  local remaining

  if [[ "${part}" -lt 0 || "${part}" -ge "${PARALLEL_PARTS}" ]]; then
    echo "invalid part index: ${part}" >&2
    return 2
  fi

  offset=$((EXPECTED_BYTES * part / PARALLEL_PARTS))
  end=$((EXPECTED_BYTES * (part + 1) / PARALLEL_PARTS))
  length=$((end - offset))
  part_path="${PART_DIR}/part_$(printf '%03d' "${part}")"
  partial_path="${part_path}.partial"

  if [[ -f "${part_path}" ]] &&
     [[ "$(stat -c '%s' "${part_path}")" -eq "${length}" ]]; then
    return 0
  fi
  if [[ -f "${partial_path}" ]]; then
    partial_bytes=$(stat -c '%s' "${partial_path}")
  fi
  if [[ "${partial_bytes}" -gt "${length}" ]]; then
    echo "part ${part}: partial file is longer than expected" >&2
    return 1
  fi
  if [[ "${partial_bytes}" -eq "${length}" ]]; then
    mv "${partial_path}" "${part_path}"
    return 0
  fi

  source_offset=$((offset + partial_bytes))
  remaining=$((length - partial_bytes))
  printf 'part=%s current=%s remaining=%s offset=%s\n' \
    "${part}" "${partial_bytes}" "${remaining}" "${source_offset}"
  ssh "${SSH_ARGS[@]}" \
    "${JP_HOST}" \
    "dd if='${SOURCE_ON_JP}' iflag=skip_bytes,count_bytes skip=${source_offset} count=${remaining} bs=8M status=none" \
    >> "${partial_path}"

  if [[ "$(stat -c '%s' "${partial_path}")" -ne "${length}" ]]; then
    echo "part ${part}: resumed size mismatch" >&2
    return 1
  fi
  mv "${partial_path}" "${part_path}"
}

pids=()
for part in "${PART_INDICES[@]}"; do
  resume_part "${part}" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do
  wait "${pid}"
done
