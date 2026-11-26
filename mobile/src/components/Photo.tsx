import { Image, type ImageProps } from "expo-image";
import { color } from "@/theme";

/** A photo with a quiet placeholder colour while it loads. */
export function Photo(props: ImageProps) {
  return <Image contentFit="cover" transition={200} {...props} style={[{ backgroundColor: color.surfaceHigh }, props.style]} />;
}
