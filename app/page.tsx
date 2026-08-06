import type { Metadata } from "next";
import WorkflowAtlas from "./WorkflowAtlas";

export const metadata: Metadata = {
  metadataBase: new URL("http://localhost:3000"),
  title: "Workflow Atlas | Ren'Py Story Mapper",
  description: "A living dependency map for the Ren'Py Story Mapper project.",
  openGraph: {
    title: "Ren'Py Story Mapper — Workflow Atlas",
    description: "See every dependency. Trace every failure.",
    images: [{ url: "/og.png", width: 1536, height: 1024 }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Ren'Py Story Mapper — Workflow Atlas",
    description: "See every dependency. Trace every failure.",
    images: ["/og.png"],
  },
};

export default function Home() {
  return <WorkflowAtlas />;
}
