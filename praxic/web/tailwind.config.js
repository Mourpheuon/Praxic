/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        paper: '#F7F4ED',
        cream: '#FCFAF5',
        linen: '#EDE8DF',
        ink: '#1C1916',
        warmgray: '#6B6560',
        seal: {
          DEFAULT: '#8C271E',
          light: '#B85450',
          wash: '#FFF5F3',
        },
        gold: '#9E7B3A',
        olive: '#4A6741',
        olivewash: '#F0F5EE',
        clay: '#C5BFB5',
        dust: '#EFEBE4',
      },
      fontFamily: {
        display: ['"Noto Serif SC"', 'serif'],
        body: ['"Microsoft YaHei"', '"Segoe UI"', 'sans-serif'],
      },
      borderRadius: {
        card: '10px',
      },
    },
  },
  plugins: [],
}
