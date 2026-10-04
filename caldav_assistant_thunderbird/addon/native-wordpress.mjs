import {Subprocess} from 'resource://gre/modules/Subprocess.sys.mjs';
import {setTimeout,clearTimeout} from 'resource://gre/modules/Timer.sys.mjs';
// No shell and no interpolated command string. JSON travels as base64 data.
export async function wpCli(operation,payload,config) {
  const data=btoa(unescape(encodeURIComponent(JSON.stringify({operation,payload}))));
  const script=`$d=json_decode(base64_decode('${data}'),true); $p=$d['payload'];
if($d['operation']==='test'){$r=['transport'=>'wp-cli','site'=>get_bloginfo('name')];}
elseif($d['operation']==='full-test'){
 $post=0;$media=0;$file=null;$checks=[];
 try{
  $post=wp_insert_post(['post_title'=>'TEST '.$p['id'],'post_content'=>'TEST create','post_status'=>'draft'],true);if(is_wp_error($post)){throw new Exception($post->get_error_message());}$checks[]='create draft';
  if(get_post($post)->post_content!=='TEST create'){throw new Exception('POST_READBACK_MISMATCH');}$checks[]='read draft';
  $update=wp_update_post(['ID'=>$post,'post_content'=>'TEST updated'],true);if(is_wp_error($update)||get_post($post)->post_content!=='TEST updated'){throw new Exception('POST_UPDATE_READBACK_MISMATCH');}$checks[]='update/readback';
  $upload=wp_upload_bits('TEST-'.$p['id'].'.png',null,base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ8sAAAAASUVORK5CYII='));
  if($upload['error']){throw new Exception($upload['error']);}$file=$upload['file'];
  $media=wp_insert_attachment(['post_title'=>'TEST media','post_mime_type'=>'image/png','post_status'=>'inherit'],$file,0,true);
  if(is_wp_error($media)){throw new Exception($media->get_error_message());}if(get_post($media)->post_type!=='attachment'){throw new Exception('MEDIA_READBACK_MISMATCH');}$checks[]='upload/read media';
 }finally{
  $failures=[];
  if(is_int($media)&&$media){if(!wp_delete_attachment($media,true)){$failures[]='TEST_MEDIA_CLEANUP_FAILED';}else{$checks[]='delete media';}}
  elseif($file){@unlink($file);}
  if(is_int($post)&&$post){if(!wp_delete_post($post,true)){$failures[]='TEST_POST_CLEANUP_FAILED';}else{$checks[]='delete draft';}}
  if($failures){throw new Exception(implode(';',$failures));}
 }
 $r=['transport'=>'wp-cli','checks'=>$checks];
}
elseif($d['operation']==='createLog'){$slug='caldav-session-'.$p['id'];$old=get_posts(['name'=>$slug,'post_type'=>'post','post_status'=>'any','numberposts'=>1]);
if($old){$r=['id'=>$old[0]->ID];}else{$id=wp_insert_post(['post_title'=>$p['title']??'工作记录','post_content'=>$p['content']??wp_json_encode($p['session']),'post_status'=>'draft','post_name'=>$slug],true);if(is_wp_error($id)){fwrite(STDERR,$id->get_error_message());exit(1);}$r=['id'=>$id];}}
else{fwrite(STDERR,'Unsupported operation');exit(1);} echo wp_json_encode($r);`;
  const command=config.wpExecutable || await Subprocess.pathSearch('wp');
  const process=await Subprocess.call({command,arguments:[`--path=${config.wpPath}`,'--no-color','eval',script],stderr:'pipe'});
  const watchdog=setTimeout(()=>process.kill(),15000);
  const read=async pipe=>{let text='',part;while((part=await pipe.readString())!=='')text+=part;return text;};
  let stdout,stderr,result;
  try{[stdout,stderr,result]=await Promise.all([read(process.stdout),read(process.stderr),process.wait()]);}finally{clearTimeout(watchdog);}
  if(result.exitCode!==0)throw new Error(`WP-CLI exit ${result.exitCode}: ${stderr.slice(0,500)}`);
  return JSON.parse(stdout);
}
