import { useEffect, useRef } from 'react';

/**
 * Одноразовый «салют» после успешного оформления заказа: ~40 частиц, 1.6 секунды.
 * Полностью на canvas, без зависимостей; отключается при prefers-reduced-motion.
 */
export function Confetti({ className = 'confetti-layer' }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = window.innerWidth;
    const height = window.innerHeight;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    const palette = ['--m3-primary', '--m3-secondary', '--m3-tertiary'].map(name =>
      getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#4C8DFF');
    const originX = width / 2;
    const originY = Math.max(120, height * 0.32);
    const particles = Array.from({ length: 42 }, (_, index) => {
      const angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.15;
      const speed = 4 + Math.random() * 6;
      return {
        x: originX + (Math.random() - 0.5) * 40,
        y: originY + (Math.random() - 0.5) * 20,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        size: 3 + Math.random() * 4,
        spin: (Math.random() - 0.5) * 0.3,
        rotation: Math.random() * Math.PI,
        color: palette[index % palette.length],
      };
    });

    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const elapsed = now - started;
      context.clearRect(0, 0, width, height);
      context.globalAlpha = Math.max(0, 1 - elapsed / 1600);
      for (const particle of particles) {
        particle.vy += 0.16;
        particle.vx *= 0.992;
        particle.x += particle.vx;
        particle.y += particle.vy;
        particle.rotation += particle.spin;
        context.save();
        context.translate(particle.x, particle.y);
        context.rotate(particle.rotation);
        context.fillStyle = particle.color;
        context.fillRect(-particle.size / 2, -particle.size / 2, particle.size, particle.size * 1.6);
        context.restore();
      }
      context.globalAlpha = 1;
      if (elapsed < 1700) frame = window.requestAnimationFrame(tick);
      else context.clearRect(0, 0, width, height);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
