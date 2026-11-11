import UsersList from "@/components/admin/UsersList";

export const metadata = { title: "Users · Admin · Accnomos", robots: { index: false, follow: false } };

export default function Page() {
  return <UsersList />;
}
