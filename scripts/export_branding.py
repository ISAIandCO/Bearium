"""Export approved Bearium artwork. Requires CairoSVG and ImageMagick convert."""
from pathlib import Path
import base64, re, subprocess, tempfile, xml.etree.ElementTree as ET
import cairosvg
root=Path(__file__).resolve().parents[1] / 'branding/android'
workspace = tempfile.TemporaryDirectory(prefix='bearium-icons-')
tmpdir = Path(workspace.name)
ns='http://www.w3.org/2000/svg'
mono=ET.parse(root/'source/bearium-monochrome.svg').getroot()
for p in mono:
 p.set('fill','#ffffff')
mono.set('viewBox','0 0 1254 1254')
ET.register_namespace('',ns)
ET.ElementTree(mono).write(root/'source/bearium-monochrome.svg',encoding='unicode')
body=''.join(ET.tostring(p,encoding='unicode') for p in mono)
svgstart='<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="108" height="108" viewBox="0 0 108 108">'
monoart='<g transform="translate(21.396 21.396) scale(.052)">'+body+'</g>'
(root/'bearium-monochrome.svg').write_text(svgstart+monoart+'</svg>')
# Color SVG is a lossless raster wrapper, not a vector tracing.
encoded=base64.b64encode((root/'source/bearium-color.png').read_bytes()).decode()
art='<image x="21.396" y="21.396" width="65.208" height="65.208" xlink:href="data:image/png;base64,'+encoded+'"/>'
(root/'bearium-foreground.svg').write_text(svgstart+art+'</svg>')
bg='<defs><linearGradient id="bg" x2="0" y2="1"><stop stop-color="#960719"/><stop offset="1" stop-color="#30030b"/></linearGradient></defs><path fill="url(#bg)" d="M0 0H108V108H0Z"/>'
# Store/legacy crop corresponds to the launcher's 72dp visible viewport.
store=svgstart+bg+'<g transform="translate(-27 -27) scale(1.5)">'+art+'</g></svg>'
(root/'bearium-store.svg').write_text(store)
cairosvg.svg2png(bytestring=(svgstart+art+'</svg>').encode(),write_to=str(tmpdir / 'foreground.png'),output_width=432,output_height=432)
subprocess.run(['convert',str(tmpdir / 'foreground.png'),'-define','webp:lossless=true',str(root/'bearium-foreground.webp')],check=True)
cairosvg.svg2png(bytestring=store.encode(),write_to=str(root/'bearium-play-512.png'),output_width=512,output_height=512)
for density,size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
 for round_ in [False,True]:
  shape='<circle cx="54" cy="54" r="54"/>' if round_ else '<rect width="108" height="108" rx="23"/>'
  s=store.replace(bg,'<defs><clipPath id="mask">'+shape+'</clipPath></defs><g clip-path="url(#mask)">'+bg).replace('</svg>','</g></svg>')
  tmp=str(tmpdir / 'legacy.png')
  cairosvg.svg2png(bytestring=s.encode(),write_to=tmp,output_width=size,output_height=size)
  subprocess.run(['convert',tmp,'-define','webp:lossless=true',str(root/f'bearium-{"round-" if round_ else ""}{density}.webp')],check=True)
android='http://schemas.android.com/apk/res/android'
ET.register_namespace('android',android)
a=lambda name:'{'+android+'}'+name
vec=ET.Element('vector',{a('width'):'108dp',a('height'):'108dp',a('viewportWidth'):'108',a('viewportHeight'):'108'})
g=ET.SubElement(vec,'group',{a('translateX'):'21.396',a('translateY'):'21.396',a('scaleX'):'.052',a('scaleY'):'.052'})
for p in mono:
 t=re.fullmatch(r'translate\(([-\d.]+),([-\d.]+)\)',p.get('transform',''))
 parent=ET.SubElement(g,'group',{a('translateX'):t[1],a('translateY'):t[2]}) if t else g
 ET.SubElement(parent,'path',{a('fillColor'):'#FFFFFFFF',a('pathData'):p.get('d')})
ET.indent(vec)
ET.ElementTree(vec).write(root/'bearium-monochrome.xml',encoding='unicode')
(root/'bearium-foreground.xml').write_text('<bitmap xmlns:android="http://schemas.android.com/apk/res/android" android:src="@drawable/bearium_artwork" android:gravity="fill" android:filter="true"/>\n')
(root/'bearium-background.xml').write_text('<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle"><gradient android:angle="270" android:startColor="#960719" android:endColor="#30030b"/></shape>\n')
# Review sheet rendered from the actual packaged assets.
parts=[]
for i,(name,color,content) in enumerate([('Round','#650e20',art),('Rounded square','#650e20',art),('Themed light','#e5d5e8',monoart.replace('#ffffff','#382640')),('Themed dark','#302536',monoart)]):
 shape='<circle cx="54" cy="54" r="36"/>' if i==0 else '<rect x="18" y="18" width="72" height="72" rx="18"/>'
 parts.append(f'<g transform="translate({i*120} 0)"><defs><clipPath id="c{i}">{shape}</clipPath></defs><g clip-path="url(#c{i})"><rect width="108" height="108" fill="{color}"/>'+content+f'</g><text x="54" y="116" text-anchor="middle" font-size="9" fill="#eee">{name}</text></g>')
s='<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="480" height="128"><rect width="480" height="128" fill="#18181b"/>'+''.join(parts)+'</svg>'
cairosvg.svg2png(bytestring=s.encode(),write_to=str(root/'preview.png'),output_width=1440,output_height=384)

# Keep SVG wrappers small and editable; the PNG source remains alongside them.
for name in ('bearium-foreground.svg', 'bearium-store.svg'):
 path = root / name
 path.write_text(path.read_text().replace('data:image/png;base64,' + encoded, 'source/bearium-color.png'))
workspace.cleanup()
