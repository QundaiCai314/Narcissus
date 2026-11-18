import type {MetadataRoute} from 'next';
export default function manifest():MetadataRoute.Manifest{return {name:'Narcissus',short_name:'Narcissus',description:'从阅读到理解',start_url:'/',display:'standalone',background_color:'#f5f1e8',theme_color:'#514741',icons:[{src:'/icon.svg',sizes:'any',type:'image/svg+xml',purpose:'any'}]};}
