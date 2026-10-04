export function createWordPress(fetcher,wpCli) {
  const requestFetch=(url,options)=>fetcher(url,{...options,signal:AbortSignal.timeout(15000)});
  async function rest(operation,payload,config) {
    if (!['test','createLog','full-test'].includes(operation)) throw new Error('UNKNOWN_WORDPRESS_OPERATION');
    const headers = {'Content-Type':'application/json','Authorization':`Basic ${btoa(unescape(encodeURIComponent(`${config.username}:${config.password}`)))}`};
    const url = `${config.url.replace(/\/$/,'')}/wp-json/wp/v2/`;
    if(operation==='full-test') {
      const request=async(path,options={})=>{
        let response;try{response=await requestFetch(url+path,{...options,headers:{...headers,...options.headers}});}catch(error){error.network=true;throw error;}
        if(!response.ok){const error=new Error(`WordPress ${response.status}`);error.status=response.status;throw error;}return response.json();
      };
      let post=null,media=null;const checks=[];
      try {
        post=await request('posts',{method:'POST',body:JSON.stringify({title:`TEST ${payload.id}`,content:'TEST create',status:'draft'})});checks.push('create draft');
        const read=await request(`posts/${post.id}?context=edit`);if(read.content.raw!=='TEST create')throw new Error('POST_READBACK_MISMATCH');checks.push('read draft');
        await request(`posts/${post.id}`,{method:'POST',body:JSON.stringify({content:'TEST updated'})});
        const updated=await request(`posts/${post.id}?context=edit`);if(updated.content.raw!=='TEST updated')throw new Error('POST_UPDATE_READBACK_MISMATCH');checks.push('update/readback');
        const bytes=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ8sAAAAASUVORK5CYII='),c=>c.charCodeAt(0));
        media=await request('media',{method:'POST',headers:{'Content-Type':'image/png','Content-Disposition':`attachment; filename="TEST-${payload.id}.png"`},body:bytes});
        const readMedia=await request(`media/${media.id}`);if(readMedia.id!==media.id)throw new Error('MEDIA_READBACK_MISMATCH');checks.push('upload/read media');
      } finally {
        const failures=[];
        if(media)try{await request(`media/${media.id}?force=true`,{method:'DELETE'});checks.push('delete media');}catch(error){failures.push(error.message);}
        if(post)try{await request(`posts/${post.id}?force=true`,{method:'DELETE'});checks.push('delete draft');}catch(error){failures.push(error.message);}
        if(failures.length)throw new Error(`TEST_CLEANUP_FAILED ${failures.join('; ')}`);
      }
      return {transport:'rest',checks};
    }
    const request = operation === 'test' ? {method:'GET',headers} : {method:'POST',headers,body:JSON.stringify({title:payload.title ?? '工作记录',content:payload.content ?? JSON.stringify(payload.session),status:'draft',slug:`caldav-session-${payload.id}`})};
    let response;
    try {
      // Stable slug provides read-before-create retry deduplication.
      if (operation === 'createLog') {
        const previous = await requestFetch(`${url}posts?slug=${encodeURIComponent(`caldav-session-${payload.id}`)}&status[]=draft&status[]=publish&status[]=pending&status[]=private&status[]=future&context=edit`,{headers});
        // A restricted account may receive 400 while asking for edit-context
        // posts/statuses it cannot list. Continue to the real create request so
        // WordPress returns the authoritative permission response (401/403),
        // which the transport policy can classify and fall back from.
        if (!previous.ok && previous.status !== 400) {const error=new Error(`WordPress ${previous.status}`); error.status=previous.status; throw error;}
        const matches=await previous.json(); if (matches.length) return matches[0];
      }
      response = await requestFetch(`${url}${operation === 'test' ? 'users/me' : 'posts'}`,request);
    } catch(error) {if (!error.status) error.network=true; throw error;}
    if (!response.ok) {const error=new Error(`WordPress ${response.status}`);error.status=response.status;throw error;}
    return response.json();
  }
  return {rest,'wp-cli':async (...args)=>{if (!wpCli) throw new Error('WP_CLI_ADAPTER_NOT_AVAILABLE');return wpCli(...args);}};
}
