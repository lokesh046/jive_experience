import * as Device from "expo-device";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { Alert } from "react-native";
import { api } from "./api";
import type { AuthUser } from "./types";

const SIZE = 800; // the server crops to a square and keeps it small; this keeps the upload far under 2 MB

export const canTakePhoto = Device.isDevice; // the simulator has no camera

/** Pick or take a photo, shrink it, and upload it. Returns the updated account, or null if cancelled. */
export async function chooseAvatar(source: "library" | "camera"): Promise<AuthUser | null> {
  if (source === "camera") {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Camera access is off", "Allow JIVE to use the camera in Settings to take a profile picture.");
      return null;
    }
  }
  const options: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], allowsEditing: true, aspect: [1, 1], quality: 1 };
  const picked = source === "camera" ? await ImagePicker.launchCameraAsync(options) : await ImagePicker.launchImageLibraryAsync(options);
  if (picked.canceled || !picked.assets[0]) return null;

  const ctx = ImageManipulator.manipulate(picked.assets[0].uri).resize({ width: SIZE });
  const rendered = await ctx.renderAsync();
  const out = await rendered.saveAsync({ format: SaveFormat.JPEG, compress: 0.85 });

  const blob = await (await fetch(out.uri)).blob();
  return api<AuthUser>("users/me/avatar", { method: "PUT", file: { blob, contentType: "image/jpeg" } });
}

export function removeAvatar(): Promise<AuthUser> {
  return api<AuthUser>("users/me/avatar", { method: "DELETE" });
}
