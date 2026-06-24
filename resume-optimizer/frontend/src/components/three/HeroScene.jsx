import { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';

/* Floating résumé sheets in warm light. Loaded lazily — never in the
   initial bundle — and only on capable devices (see HeroVisual). */

const PAPER = '#FFFFFF';
const INK = '#20242A';
const INK_SOFT = '#6A7078';
const GREEN = '#0D9488';
const AMBER = '#A16207';

function Line({ x = 0, y, w, h = 0.055, color = INK_SOFT }) {
  return (
    <mesh position={[x, y, 0.028]}>
      <boxGeometry args={[w, h, 0.012]} />
      <meshStandardMaterial color={color} roughness={0.9} />
    </mesh>
  );
}

function Sheet({ position, rotation, phase = 0, speed = 0.6, amp = 0.12, accent = GREEN }) {
  const ref = useRef();

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime();
    if (!ref.current) return;
    ref.current.position.y = position[1] + Math.sin(t * speed + phase) * amp;
    ref.current.rotation.z = rotation[2] + Math.sin(t * speed * 0.7 + phase) * 0.02;
  });

  return (
    <group ref={ref} position={position} rotation={rotation}>
      {/* paper */}
      <mesh castShadow>
        <boxGeometry args={[2.1, 2.9, 0.035]} />
        <meshStandardMaterial color={PAPER} roughness={0.85} />
      </mesh>
      {/* name + contact */}
      <Line y={1.15} w={1.1} h={0.12} color={INK} />
      <Line y={0.95} w={0.8} h={0.045} />
      {/* accent rule */}
      <Line y={0.74} w={1.6} h={0.035} color={accent} />
      {/* body lines */}
      <Line y={0.5} w={1.6} />
      <Line y={0.32} w={1.45} />
      <Line y={0.14} w={1.55} />
      <Line y={-0.1} w={0.9} h={0.07} color={INK} />
      <Line y={-0.32} w={1.6} />
      <Line y={-0.5} w={1.5} />
      <Line y={-0.68} w={1.25} />
      <Line y={-0.95} w={0.7} h={0.07} color={INK} />
      <Line y={-1.17} w={1.5} />
    </group>
  );
}

function Scene() {
  const group = useRef();

  // Ease the whole stack toward the pointer for parallax.
  useFrame(({ pointer }) => {
    if (!group.current) return;
    group.current.rotation.y += (pointer.x * 0.22 - group.current.rotation.y) * 0.05;
    group.current.rotation.x += (-pointer.y * 0.14 - group.current.rotation.x) * 0.05;
  });

  return (
    <>
      <ambientLight intensity={0.85} />
      <directionalLight position={[4, 6, 6]} intensity={1.4} color="#FEF9E7" />
      <directionalLight position={[-6, -2, 4]} intensity={0.35} color="#CCFBF1" />
      <group ref={group}>
        <Sheet position={[-1.15, 0.1, -1.2]} rotation={[0.04, 0.35, 0.06]} phase={2.1} accent={AMBER} />
        <Sheet position={[1.05, -0.15, -0.4]} rotation={[0.02, -0.28, -0.05]} phase={4.2} />
        <Sheet position={[0, 0.05, 0.6]} rotation={[0.01, 0.04, 0.015]} phase={0} amp={0.16} />
      </group>
    </>
  );
}

export default function HeroScene() {
  return (
    <Canvas
      dpr={[1, 1.75]}
      camera={{ position: [0, 0, 7], fov: 38 }}
      gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      style={{ background: 'transparent' }}
      aria-hidden="true"
    >
      <Scene />
    </Canvas>
  );
}
