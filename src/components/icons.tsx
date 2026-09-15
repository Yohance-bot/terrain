import { useId, type ReactNode } from 'react';
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

import { ui } from '@/theme';

/**
 * TerraRun's own icon set: one 24px grid, one 1.75 stroke, round caps.
 *
 * Drawn for running rather than borrowed: the profile is a race bib, a streak
 * is tally marks, a goal is the finish tape, a ghost is a recorded route.
 */

export type IconProps = { size?: number; color?: string; strokeWidth?: number };

function Icon({ size = 24, color = ui.icon, strokeWidth = 1.75, children }: IconProps & { children: ReactNode }) {
  const id = `icon-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const ink = color === ui.icon ? `url(#${id})` : color;
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={ink} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      <Defs>
        <LinearGradient id={id} x1="0" y1="1" x2="1" y2="0">
          <Stop offset="0" stopColor={ui.iconGradient[0]} />
          <Stop offset="0.55" stopColor={ui.iconGradient[1]} />
          <Stop offset="1" stopColor={ui.iconGradient[2]} />
        </LinearGradient>
      </Defs>
      {children}
    </Svg>
  );
}

export const MapIcon = (p: IconProps) => (
  <Icon {...p}>
    <Rect x={3.5} y={3.5} width={17} height={17} rx={4} />
    <Path d="M7 16c2.5 0 2-5 5-5s2.5-4 5-4" />
    <Circle cx={7} cy={16} r={1.5} fill={p.color ?? ui.icon} stroke="none" />
  </Icon>
);

export const FriendsIcon = (p: IconProps) => (
  <Icon {...p}>
    <Circle cx={9} cy={8.5} r={3} />
    <Circle cx={16.5} cy={10} r={2.5} />
    <Path d="M3.5 19c.8-3.4 3-5 5.5-5s4.7 1.6 5.5 5" />
    <Path d="M14.8 14.6c.5-.1 1.1-.1 1.7-.1 2 0 3.6 1.3 4.2 4.5" />
  </Icon>
);

/** A race bib: the athlete's number, pinned on. */
export const ProfileIcon = (p: IconProps) => (
  <Icon {...p}>
    <Rect x={4} y={5} width={16} height={14} rx={2.5} />
    <Circle cx={7.2} cy={8.2} r={0.9} fill={p.color ?? ui.icon} stroke="none" />
    <Circle cx={16.8} cy={8.2} r={0.9} fill={p.color ?? ui.icon} stroke="none" />
    <Path d="M8 13h8M9.5 16h5" />
  </Icon>
);

export const StartIcon = (p: IconProps) => (
  <Icon strokeWidth={2} {...p}>
    <Path d="M10 6l7 6-7 6" />
    <Path d="M3.5 9h3M2.5 12h4.5M3.5 15h3" />
  </Icon>
);

export const LayersIcon = (p: IconProps) => (
  <Icon {...p}>
    <Rect x={3.5} y={9.5} width={11} height={11} rx={2.5} />
    <Path d="M8 6.5V6a2.5 2.5 0 0 1 2.5-2.5H18A2.5 2.5 0 0 1 20.5 6v7.5A2.5 2.5 0 0 1 18 16h-.5" />
  </Icon>
);

/** A ghost is a route someone already ran: a dashed trail and where it began. */
export const GhostIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M6.5 17.5C6.5 11 11 11 13 11s5.5-.5 5.5-6.5" strokeDasharray="2.2 2.8" />
    <Circle cx={6.5} cy={18} r={2.2} />
    <Path d="M16 6.5 18.5 4 21 6.5" />
  </Icon>
);

/** Tally marks, crossed: weeks kept. */
export const StreakIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M6 5v14M10 5v14M14 5v14M18 5v14" />
    <Path d="M4 16 20 8" />
  </Icon>
);

/** Finish posts and the tape between them. */
export const GoalIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M5 20.5V4.5M19 20.5V4.5" />
    <Path d="M5 8c3.5 2.6 10.5 2.6 14 0" />
  </Icon>
);

export const LogIcon = (p: IconProps) => (
  <Icon {...p}>
    <Rect x={5} y={3.5} width={14} height={17} rx={2} />
    <Path d="M9 3.5v17" />
    <Path d="M12 8h4M12 11.5h4" />
  </Icon>
);

export const DuelIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M3.5 7l5 5-5 5" />
    <Path d="M20.5 7l-5 5 5 5" />
  </Icon>
);

export const SettingsIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
    <Circle cx={15} cy={7} r={2} />
    <Circle cx={9} cy={17} r={2} />
  </Icon>
);

export const RecenterIcon = (p: IconProps) => (
  <Icon {...p}>
    <Circle cx={12} cy={12} r={3} />
    <Path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4" />
  </Icon>
);

export const SearchIcon = (p: IconProps) => (
  <Icon strokeWidth={2} {...p}>
    <Circle cx={10.5} cy={10.5} r={6} />
    <Path d="m15 15 5 5" />
  </Icon>
);

export const PlusIcon = (p: IconProps) => (
  <Icon strokeWidth={2} {...p}>
    <Path d="M12 5v14M5 12h14" />
  </Icon>
);

export const MinusIcon = (p: IconProps) => (
  <Icon strokeWidth={2} {...p}>
    <Path d="M5 12h14" />
  </Icon>
);

export const ChevronRightIcon = (p: IconProps) => (
  <Icon strokeWidth={2.2} {...p}>
    <Path d="m9 6 6 6-6 6" />
  </Icon>
);

export const ChevronLeftIcon = (p: IconProps) => (
  <Icon strokeWidth={2.2} {...p}>
    <Path d="M15 5l-7 7 7 7" />
  </Icon>
);

export const CloseIcon = (p: IconProps) => (
  <Icon strokeWidth={2.2} {...p}>
    <Path d="M6 6l12 12M18 6 6 18" />
  </Icon>
);

/** A running shoe in profile, heel to toe. */
export const ShoeIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M3.5 17h11.2c2.4 0 4.3-.7 5.8-2l.6-.6c.3-.3.2-.8-.2-1l-4.2-2.2-2.2-3.3a.9.9 0 0 0-1.2-.2l-1.6 1-3.4.5-2.7-1.8a.8.8 0 0 0-1.2.6L3.5 17Z" />
    <Path d="M3.5 20h17" />
  </Icon>
);

/** A medal on its ribbon, for a personal record. */
export const RecordIcon = (p: IconProps) => (
  <Icon {...p}>
    <Circle cx={12} cy={15} r={5} />
    <Path d="M9 10.5 7 3.5h3l2 4.5 2-4.5h3l-2 7" />
  </Icon>
);

export const NoteIcon = (p: IconProps) => (
  <Icon {...p}>
    <Path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" />
    <Path d="m13.5 6.5 4 4" />
  </Icon>
);

export const SunIcon = (p: IconProps) => <Icon {...p}>
  <Circle cx={12} cy={12} r={4} /><Path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
</Icon>;
export const MoonIcon = (p: IconProps) => <Icon {...p}>
  <Path d="M20 14A8.5 8.5 0 0 1 10 3a8.5 8.5 0 1 0 10 11Z" />
</Icon>;
