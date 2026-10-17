/* The 60-second cutdown: the same scenes with their own short narration lines (narration.json → cut_scenes), each scene
   compressed to the storyline's Part 5 timing. The scene components take the cutdown's voice and caption through Wrap. */
import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Spark, Title, Close, Evidence, Rules, Cards, Release, Trace, cutVoice, cutLine } from "./scenes";

const MAP: Record<number, React.FC<any>> = { 0: Spark, 1: Title, 4: Close, 5: Evidence, 7: Rules, 8: Cards, 10: Release, 12: Trace };

export const CutScene: React.FC<{ scene: number }> = ({ scene }) => {
  const Scene = MAP[scene];
  return <Scene voiceSrc={cutVoice(scene)} captionText={cutLine(scene)} cut />;
};
