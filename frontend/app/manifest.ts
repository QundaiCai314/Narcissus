import type {MetadataRoute} from 'next';
export default function manifest():MetadataRoute.Manifest{return {name:'Narcissus',short_name:'Narcissus',description:'从阅读到理解',start_url:'/',display:'standalone',background_color:'#f7f5ee',theme_color:'#405b46',icons:[{src:'/icon.svg',sizes:'any',type:'image/svg+xml',purpose:'any'}]};}
