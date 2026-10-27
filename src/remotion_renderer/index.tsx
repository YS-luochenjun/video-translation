import React, {useEffect, useState} from 'react';
import {Composition, registerRoot, useCurrentFrame, interpolate, staticFile, delayRender, continueRender, cancelRender} from 'remotion';

// Optional typography-only renderer. Tracks are supplied by the caller, never inferred here.
type Block = {
  id: string; text: string; family: string; fontSize: number; color: string;
  box: [number, number, number, number]; startFrame: number; endFrame: number;
  direction?: 'ltr' | 'rtl'; animated?: boolean; emphasize?: string;
  outline?: number; outlineColor?: string; align?: 'left' | 'center' | 'right'; emphasisColor?: string; emphasisFrame?: number;
  animationStartFrame?: number; animationEndFrame?: number;
  track?: {frame: number; x: number; y: number; rotation: number}[];
};
type Props = {width: number; height: number; fps: number; durationInFrames: number;
  fonts: {family: string; file: string}[]; blocks: Block[]};
const defaults: Props = {width:720,height:1280,fps:30,durationInFrames:150,fonts:[],blocks:[]};

function Fonts({fonts}: {fonts: Props['fonts']}) {
  const [handle] = useState(() => delayRender('Load explicit local fonts'));
  useEffect(() => {
    let active = true;
    Promise.all(fonts.map(async (font) => {
      const face = new FontFace(font.family, `url("${staticFile(font.file)}")`);
      await face.load();
      document.fonts.add(face);
    })).then(() => {if (active) continueRender(handle);}).catch(cancelRender);
    return () => {active = false;};
  }, [fonts, handle]);
  return null;
}

function TextBlock({block, frame}: {block: Block; frame: number}) {
  if (frame < block.startFrame || frame >= block.endFrame) return null;
  const local = frame - (block.animationStartFrame ?? block.startFrame);
  const length = (block.animationEndFrame ?? block.endFrame) - (block.animationStartFrame ?? block.startFrame);
  const envelope = block.animated ? Math.min((local + 1) / 8, (length - local) / 8, 1) : 1;
  const track = block.track;
  const sample = (key: 'x' | 'y' | 'rotation', fallback: number) => track?.length
    ? interpolate(frame, track.map(p => p.frame), track.map(p => p[key]), {extrapolateLeft:'clamp',extrapolateRight:'clamp'}) : fallback;
  const [x,y,width,height] = block.box;
  const emphasized = block.emphasize && block.text.includes(block.emphasize) ? block.text.split(block.emphasize) : null;
  return <div dir={block.direction ?? 'ltr'} style={{position:'absolute',left:sample('x',x),top:sample('y',y),width,height,
    display:'flex',alignItems:'center',justifyContent: block.align === 'left' ? 'flex-start' : block.align === 'right' ? 'flex-end' : 'center',textAlign:block.align ?? 'center',fontFamily:block.family,
    fontSize:block.fontSize,fontWeight:400,lineHeight:1.2,color:block.color,whiteSpace:'pre',
    opacity:envelope,transform:`rotate(${sample('rotation',0)}deg) scale(${block.animated ? .96 + .04 * envelope : 1})`,
    WebkitTextStroke:`${block.outline ?? 1.4}px ${block.outlineColor ?? '#321b39'}`,paintOrder:'stroke fill'}}>
      <span>{emphasized ? <>{emphasized[0]}<span style={{color: frame >= (block.emphasisFrame ?? block.startFrame + 25) ? (block.emphasisColor ?? '#ffe56a') : block.color}}>{block.emphasize}</span>{emphasized.slice(1).join(block.emphasize)}</> : block.text}</span>
  </div>;
}
function Layer(props: Props) {
  const frame = useCurrentFrame();
  return <><Fonts fonts={props.fonts}/>{props.blocks.map(block => <TextBlock key={block.id} block={block} frame={frame}/>)}</>;
}
registerRoot(() => <Composition id="Typography" component={Layer} defaultProps={defaults}
  width={720} height={1280} fps={30} durationInFrames={150}
  calculateMetadata={({props}) => ({width:props.width,height:props.height,fps:props.fps,durationInFrames:props.durationInFrames})}/>);
