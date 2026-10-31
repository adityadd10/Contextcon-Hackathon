import {registerRoot, Composition} from 'remotion';
import {Pitch, totalFrames, FPS} from './Pitch';

const Root = () => (
  <Composition id="Pitch" component={Pitch} durationInFrames={totalFrames} fps={FPS} width={1920} height={1080} />
);

registerRoot(Root);
