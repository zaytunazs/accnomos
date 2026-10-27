"use client";

import { RuntimeErrorNote } from "@/components/States";
import { useHome } from "./HomeData";

/** Signed-in Home errors use the one shared strip: 401 signs in again, 5xx quotes its reference. */
export default function HomeError() {
  const home = useHome();
  if (home.mode !== "error") return null;
  return <RuntimeErrorNote message={home.message} title="Couldn't load your books" />;
}
