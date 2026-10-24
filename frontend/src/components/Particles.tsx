import { useEffect, useRef } from 'react';

/**
 * Частицы на фоне hero: ~26 точек и «искр» цветов палитры, медленный дрейф вверх.
 * Canvas, devicePixelRatio, пауза во вкладке; отключается при prefers-reduced-motion.
 */
export function Particles({ className = 'hero-particles', count = 26 }: { className?: string; count?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas?.parentElement;
    if (!canvas || !host) return;
    const context = canvas.getContext('2d');
    if (!context) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // Настройка «уменьшить движение»: не анимируем, но частицы всё равно рисуем.
      const reducedRatio = Math.min(window.devicePixelRatio || 1, 2);
      const reducedWidth = host.clientWidth;
      const reducedHeight = host.clientHeight;
      canvas.width = Math.round(reducedWidth * reducedRatio);
      canvas.height = Math.round(reducedHeight * reducedRatio);
      canvas.style.width = `${reducedWidth}px`;
      canvas.style.height = `${reducedHeight}px`;
      context.setTransform(reducedRatio, 0, 0, reducedRatio, 0, 0);
      const reducedPalette = ['--m3-primary', '--m3-secondary', '--m3-tertiary'].map(name =>
        getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#4C8DFF');
      for (let index = 0; index < count; index += 1) {
        context.globalAlpha = 0.45;
        context.fillStyle = reducedPalette[index % reducedPalette.length];
        context.beginPath();
        context.arc(Math.random() * reducedWidth, Math.random() * reducedHeight, 1.8 + Math.random() * 2, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;
      return;
    }

    let frame = 0;
    let width = 0;
    let height = 0;
    type Particle = {
      x: number; y: number; radius: number; speed: number; drift: number;
      phase: number; color: string; diamond: boolean; glow: boolean;
    };
    let particles: Particle[] = [];
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
      particles = Array.from({ length: count }, (_, index) => {
        const radius = 1.6 + Math.random() * 2.6;
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          radius,
          speed: 0.12 + Math.random() * 0.32,
          drift: 0.3 + Math.random() * 0.6,
          phase: Math.random() * Math.PI * 2,
          color: palette[index % palette.length],
          diamond: index % 3 === 0,
          glow: radius > 3,
        };
      });
    };

    const draw = () => {
      context.clearRect(0, 0, width, height);
      for (const particle of particles) {
        particle.y -= particle.speed;
        particle.phase += 0.01;
        particle.x += Math.sin(particle.phase) * particle.drift * 0.3;
        if (particle.y < -8) { particle.y = height + 8; particle.x = Math.random() * width; }
        if (particle.x < -8) particle.x = width + 8;
        if (particle.x > width + 8) particle.x = -8;
        // Заметно, но не ярко: «дыхание» от 0.32 до 0.85.
        context.globalAlpha = 0.34 + (Math.sin(particle.phase) + 1) * 0.25;
        context.fillStyle = particle.color;
        if (particle.glow) {
          context.shadowColor = particle.color;
          context.shadowBlur = 10;
        }
        if (particle.diamond) {
          const size = particle.radius * 1.9;
          context.beginPath();
          context.moveTo(particle.x, particle.y - size);
          context.lineTo(particle.x + size, particle.y);
          context.lineTo(particle.x, particle.y + size);
          context.lineTo(particle.x - size, particle.y);
          context.closePath();
          context.fill();
        } else {
          context.beginPath();
          context.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
          context.fill();
        }
        context.shadowBlur = 0;
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
