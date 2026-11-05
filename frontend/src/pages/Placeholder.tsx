export default function Placeholder({ title, owner }: { title: string; owner?: string }) {
  return (
    <section className="placeholder">
      <h2>{title}</h2>
      <p>{owner ? `${owner} 담당 화면이 들어올 자리입니다.` : '주소를 다시 확인해 주세요.'}</p>
    </section>
  )
}
