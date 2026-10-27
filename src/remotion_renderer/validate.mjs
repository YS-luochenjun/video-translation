export function validateProps(props) {
  for (const key of ['width','height','durationInFrames']) {
    if (!Number.isSafeInteger(props[key]) || props[key] <= 0) throw new Error(`Invalid ${key}`);
  }
  if (!Number.isFinite(props.fps) || props.fps <= 0) throw new Error('Invalid fps');
  if (!Array.isArray(props.fonts) || !props.fonts.length) throw new Error('Explicit fonts required');
  const families = new Set();
  for (const font of props.fonts) {
    if (typeof font.family !== 'string' || !font.family || families.has(font.family)
      || typeof font.file !== 'string' || !/^[\w.-]+\.(ttf|otf|woff2?)$/.test(font.file)
      || font.file.includes('..')) throw new Error('Invalid local font');
    families.add(font.family);
  }
  if (!Array.isArray(props.blocks) || !props.blocks.length) throw new Error('No text instances');
  const ids = new Set();
  for (const b of props.blocks) {
    if (typeof b.id !== 'string' || !b.id || ids.has(b.id) || typeof b.text !== 'string' || !b.text.trim()) throw new Error('Invalid text instance');
    ids.add(b.id);
    if (!families.has(b.family) || !Number.isFinite(b.fontSize) || b.fontSize <= 0) throw new Error('Invalid text font');
    if (![b.startFrame,b.endFrame].every(Number.isSafeInteger) || b.startFrame < 0 || b.endFrame <= b.startFrame || b.endFrame > props.durationInFrames) throw new Error('Invalid frame interval');
    if (!Array.isArray(b.box) || b.box.length !== 4 || !b.box.every(Number.isFinite) || b.box[2] <= 0 || b.box[3] <= 0) throw new Error('Invalid box');
    if (b.direction && !['ltr','rtl'].includes(b.direction)) throw new Error('Invalid text direction');
    if (b.box[0] < 0 || b.box[1] < 0 || b.box[0]+b.box[2] > props.width || b.box[1]+b.box[3] > props.height) throw new Error('Box exceeds frame');
    if (b.align && !['left','center','right'].includes(b.align)) throw new Error('Invalid alignment');
    if (b.animated !== undefined && typeof b.animated !== 'boolean') throw new Error('Invalid animation flag');
    if (b.outline !== undefined && (!Number.isFinite(b.outline) || b.outline < 0 || b.outline > 12)) throw new Error('Invalid outline');
    // An event may precede or follow this shot when an instance spans cuts.
    if (b.emphasisFrame !== undefined && !Number.isSafeInteger(b.emphasisFrame)) throw new Error('Invalid emphasis frame');
    if (b.animationStartFrame !== undefined && (!Number.isSafeInteger(b.animationStartFrame) || b.animationStartFrame > b.startFrame)) throw new Error('Invalid animation start');
    if (b.animationEndFrame !== undefined && (!Number.isSafeInteger(b.animationEndFrame) || b.animationEndFrame < b.endFrame)) throw new Error('Invalid animation end');
    if (typeof b.color !== 'string' || !/^#[\da-f]{6}$/i.test(b.color)) throw new Error('Use an explicit RGB text color');
    if (b.emphasize !== undefined && (typeof b.emphasize !== 'string' || !b.emphasize || !b.text.includes(b.emphasize))) throw new Error('Emphasis must use actual copy');
    if (b.track !== undefined) {
      if (!Array.isArray(b.track) || b.track.length < 2) throw new Error('Track requires two or more keys');
      let last = -1;
      for (const p of b.track) {
        if (!Number.isSafeInteger(p.frame) || p.frame <= last || p.frame < 0 || p.frame >= props.durationInFrames || ![p.x,p.y,p.rotation].every(Number.isFinite)) throw new Error('Invalid supplied track');
        last = p.frame;
      }
    }
  }
}

export function validateJob(job) {
  for (const key of ['runtime','bundleDirectory','publicDirectory','browserExecutable','result']) {
    if (typeof job[key] !== 'string' || !job[key]) throw new Error(`Missing ${key}`);
  }
  if (!Array.isArray(job.renders) || !job.renders.length) throw new Error('No renders');
  for (const render of job.renders) {
    if (typeof render.props !== 'string' || typeof render.output !== 'string') throw new Error('Missing props/output');
  }
}
