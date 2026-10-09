<?xml version="1.0" encoding="UTF-8"?><sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" xmlns="http://www.opengis.net/sld" xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc" version="1.0.0">
  <sld:NamedLayer>
    <sld:Name>Default Styler</sld:Name>
    <sld:UserStyle>
      <sld:Name>Default Styler</sld:Name>
      <sld:Title>Radar dBZ</sld:Title>
      <sld:FeatureTypeStyle>
        <sld:Name>name</sld:Name>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:ColorMap type="intervals">
              <sld:ColorMapEntry color="#CCCCCC" quantity="74" label="nodata" opacity="0" />
              <sld:ColorMapEntry color="#bef6fa" quantity="77" label="heikko" opacity="1" />
              <sld:ColorMapEntry color="#6cebf3" quantity="80" label="kohtalainen" opacity="1" />
              <sld:ColorMapEntry color="#58c797" quantity="88" label="kohtalainen" opacity="1" />
              <sld:ColorMapEntry color="#409857" quantity="100" label="sakea" opacity="1" />
              <sld:ColorMapEntry color="#f1f35a" quantity="112" label="sakea" opacity="1" />
              <sld:ColorMapEntry color="#dfc40a" quantity="124" label="hyvin sakea" opacity="1" />
              <sld:ColorMapEntry color="#eb951a" quantity="132" label="hyvin sakea" opacity="1" />
              <sld:ColorMapEntry color="#e85616" quantity="144" label="hyvin sakea" opacity="1" />
              <sld:ColorMapEntry color="#ce0202" quantity="156" label="hyvin sakea" opacity="1" />
              <sld:ColorMapEntry color="#830a46" quantity="168" label="hyvin sakea" opacity="1" />
              <sld:ColorMapEntry color="#fa51a5" quantity="180" label="hyvin sakea" opacity="1" />              
              <sld:ColorMapEntry color="#CCCCCC" quantity="201" label="nodata" opacity="0.2" />              
              <sld:ColorMapEntry color="#CCCCCC" quantity="255" label="nodata" opacity="0.2" />
            </sld:ColorMap>
            <sld:ContrastEnhancement/>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>