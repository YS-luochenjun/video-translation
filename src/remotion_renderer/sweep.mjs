export function sweepCenter(frame, startFrame, sweep) {
  const cycle = ((frame - startFrame) / sweep.periodFrames + sweep.phase) % 1;
  const progress = (cycle + 1) % 1;
  const directed = sweep.direction === 'right_to_left' ? 1 - progress : progress;
  return (-sweep.width / 2 + directed * (1 + sweep.width)) * 100;
}
