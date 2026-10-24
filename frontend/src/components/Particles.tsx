import { useEffect, useRef } from 'react';

/**
 * Лёгкие «пылинки» на фоне hero: 14–20 частиц, slow drift вверх, тонкие цвета палитры.
 * Canvas, devicePixelRatio, пауза во вкладке; отключается при prefers-reduced-motion.
 */
export function Particles({ className = 'hero-particles', count = 18 }: { className?: string; count?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas?.parentElement;
    if (!canvas || !host) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    let frame = 0;
    let width = 0;
    let height = 0;
    let particles: { x: number; y: number; radius: number; speed: number; drift: number; phase: number; color: string }[] = [];
    const palette = ['--m3-primary', '--m3-secondary', '--m3-tertiary'].map(name => {
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return value || '#4C8DFF';
    });

    const resize = () => {
      width = host.clientWidth;
      height = host.clientHeight;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      particles = Array.from({ length: count }, (_, index) => ({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: 1 + Math.random() * 2.2,
        speed: 0.08 + Math.random() * 0.22,
        drift: 0.25 + Math.random() * 0.5,
        phase: Math.random() * Math.PI * 2,
        color: palette[index % palette.length],
      }));
    };

    const draw = () => {
      context.clearRect(0, 0, width, height);
      for (const particle of particles) {
        particle.y -= particle.speed;
        particle.phase += 0.008;
        particle.x += Math.sin(particle.phase) * particle.drift * 0.25;
        if (particle.y < -6) { particle.y = height + 6; particle.x = Math.random() * width; }
        if (particle.x < -6) particle.x = width + 6;
        if (particle.x > width + 6) particle.x = -6;
        context.globalAlpha = 0.22 + Math.sin(particle.phase) * 0.1;
        context.fillStyle = particle.color;
        context.beginPath();
        context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;
      frame = window.requestAnimationFrame(draw);
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    frame = window.requestAnimationFrame(draw);
    const onVisibility = () => {
      window.cancelAnimationFrame(frame);
      if (!document.hidden) frame = window.requestAnimationFrame(draw);
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [count]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
