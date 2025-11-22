import React from 'react'
import Navbar from '../components/Navbar.jsx'
import Header from '../components/Header.jsx'
import Map from '../components/Map.jsx'


const Home = () => {
  return (
    <div className='flex flex-col items-center justify-center h-full bg-[url("/bg_img.png")] bg-cover bg-center'>

      <div className="fixed top-0 left-0 w-full h-20 bg-transparent z-50 shadow">
        <Navbar/>
      </div>
      <div className="fixed top-20 left-0 w-full h-full bottom-0 -z-10">
        <Map/>
      </div>

    </div>
  )
}

export default Home
