import { Link } from 'react-router-dom'

export function NotFoundScreen() {
  return (
    <section className="screen">
      <h1>Page not found</h1>
      <p>
        No screen lives at this address. <Link to="/">Go to the start page</Link>.
      </p>
    </section>
  )
}
