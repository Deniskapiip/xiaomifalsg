import { useTheme } from '../lib/theme';
import { haptic } from '../lib/telegram';
import { Icon } from './Icon';

export function ThemeToggle() {
  const theme = useTheme(state => state.theme);
  const toggle = useTheme(state => state.toggle);
  const label = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему';
  return (
    <button className="icon-button theme-toggle" type="button" aria-label={label} title={label} onClick={() => { toggle(); haptic('selection'); }}>
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={20} />
    </button>
  );
}
