import { useFocusEffect } from "expo-router";
import { useCallback, useMemo, useRef } from "react";
import { AccessibilityInfo, FlatList, type ListRenderItemInfo, type StyleProp, type ViewStyle } from "react-native";

interface Props<T> {
  data: T[];
  /** Width of one slide. */
  itemWidth: number;
  /** Space between slides, drawn by the slide itself (as a right margin) so offsets stay exact. */
  gap?: number;
  renderItem: (item: T, index: number) => React.ReactElement;
  keyOf: (item: T, index: number) => string;
  /** Called with the real position (0 to data.length - 1) whenever a slide settles. */
  onIndexChange?: (index: number) => void;
  /** Move on by itself every this many milliseconds. Off when omitted. */
  autoPlayMs?: number;
  style?: StyleProp<ViewStyle>;
}

const GLIDE_MS = 600; // how long a slide takes to settle after an automatic move

/**
 * A row of slides that goes round forever: after the last comes the first again, and before the
 * first comes the last. With one slide it just sits there. It shows the list three times, starts in
 * the middle copy, and when a slide settles in the first or last copy it quietly jumps to the same
 * slide in the middle copy. It can also advance by itself, pausing while a finger is on it, while
 * the screen is not showing, and when the phone asks for reduced motion.
 */
export function LoopCarousel<T>({ data, itemWidth, gap = 0, renderItem, keyOf, onIndexChange, autoPlayMs, style }: Props<T>) {
  const n = data.length;
  const loop = n > 1;
  const step = itemWidth + gap;
  const ref = useRef<FlatList<{ item: T; i: number; key: string }>>(null);
  const pos = useRef(loop ? n : 0);   // where we are in the tripled list
  const touching = useRef(false);

  const rows = useMemo(
    () => (loop ? [0, 1, 2] : [0]).flatMap((c) => data.map((item, i) => ({ item, i, key: `${c}-${keyOf(item, i)}` }))),
    [data, loop, keyOf],
  );

  const settle = useCallback((x: number) => {
    let at = Math.round(x / step);
    if (loop) {
      if (at < n) { at += n; ref.current?.scrollToOffset({ offset: at * step, animated: false }); }
      else if (at >= 2 * n) { at -= n; ref.current?.scrollToOffset({ offset: at * step, animated: false }); }
    }
    pos.current = at;
    onIndexChange?.(((at % n) + n) % n);
  }, [loop, n, step, onIndexChange]);

  // Move on by itself, only while this screen is showing.
  useFocusEffect(useCallback(() => {
    if (!loop || !autoPlayMs) return;
    let live = true;
    let reduce = false;
    AccessibilityInfo.isReduceMotionEnabled().then((r) => { reduce = r; }).catch(() => {});
    const id = setInterval(() => {
      if (touching.current || reduce) return;
      const from = pos.current;
      const next = from + 1;
      ref.current?.scrollToOffset({ offset: next * step, animated: true });
      // If the list did not report the end of the glide itself, settle it here.
      setTimeout(() => { if (live && !touching.current && pos.current === from) settle(next * step); }, GLIDE_MS);
    }, autoPlayMs);
    return () => { live = false; clearInterval(id); };
  }, [loop, autoPlayMs, step, settle]));

  return (
    <FlatList
      ref={ref}
      horizontal
      data={rows}
      keyExtractor={(r) => r.key}
      renderItem={({ item }: ListRenderItemInfo<{ item: T; i: number; key: string }>) => renderItem(item.item, item.i)}
      getItemLayout={(_, index) => ({ length: step, offset: step * index, index })}
      initialScrollIndex={loop ? n : 0}
      snapToInterval={step}
      decelerationRate="fast"
      disableIntervalMomentum
      showsHorizontalScrollIndicator={false}
      onScrollBeginDrag={() => { touching.current = true; }}
      onMomentumScrollEnd={(e) => { touching.current = false; settle(e.nativeEvent.contentOffset.x); }}
      style={style}
    />
  );
}
