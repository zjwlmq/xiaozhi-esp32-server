import { getServiceUrl } from '../api'
import RequestService from '../httpRequest'

function request(path, method = 'GET', data) {
  return new Promise((resolve, reject) => {
    const operation = RequestService.sendRequest()
      .sensitive()
      .url(`${getServiceUrl()}${path}`).method(method)
      .success(({ data: body }) => {
        if (body && body.code === 0) resolve(body.data)
        else reject(new Error(body?.msg || '插件配置请求失败'))
      })
      .fail(error => reject(new Error(error?.data?.msg || error?.msg || '插件配置请求失败，请稍后重试')))
      .networkFail(() => reject(new Error('暂时无法连接配置服务')))
    if (data !== undefined) operation.data(data)
    operation.send()
  })
}

export default {
  agents: () => request('/agent/list'),
  get: id => request(`/agent/${encodeURIComponent(id)}/plugin-center`),
  update: (id, plugin, patch) => request(`/agent/${encodeURIComponent(id)}/plugin-center/${encodeURIComponent(plugin)}`, 'PUT', patch)
}
